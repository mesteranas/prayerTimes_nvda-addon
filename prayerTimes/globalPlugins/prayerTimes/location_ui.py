"""Location preview and explicit place selection, with no network I/O on the GUI thread."""

import threading

import addonHandler

addonHandler.initTranslation()

import languageHandler
import ui
import wx

from . import handler
from .service import Location, PrayerError, PrayerService, StaleRequest, coordinate, search_locations


class LocationSettingsMixin:
    def make_location_settings(self, helper, values, cached_auto=None):
        self._lookup_id = 0
        self._lookup_busy = False
        self._lookup_closed = False
        self._location_ready = False
        self._location_service = PrayerService()
        self._automatic_location = cached_auto
        self._places = ()
        self._chosen_location = None
        self.auto_detect = helper.addItem(
            wx.CheckBox(self, label=_("Detect location automatically. Not accurate in all cases"))
        )
        self.auto_detect.SetValue(values["auto_detect"])
        self.auto_detect.Bind(wx.EVT_CHECKBOX, self.on_toggle_auto)
        self.location_summary = helper.addLabeledControl(
            _("Current location"), wx.TextCtrl, value="", style=wx.TE_READONLY
        )
        self.refresh_location = helper.addItem(wx.Button(self, label=_("Refresh automatic location")))
        self.refresh_location.Bind(wx.EVT_BUTTON, self.on_refresh_location)
        self.search_query = helper.addLabeledControl(
            _("City, district or postal code"), wx.TextCtrl, value=""
        )
        hint = wx.StaticText(
            self, label=_("For example: Ankara, TR or Paris, France. Search: Open-Meteo / GeoNames.")
        )
        hint.Wrap(450)
        helper.addItem(hint)
        self.search_button = helper.addItem(wx.Button(self, label=_("Search for a location")))
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search_location)
        self.search_query.Bind(wx.EVT_TEXT, self.on_search_query_changed)
        self.place_choices = helper.addLabeledControl(_("Matching locations"), wx.Choice, choices=[])
        self.place_choices.Bind(wx.EVT_CHOICE, self.on_place_selected)
        self.use_place = helper.addItem(wx.Button(self, label=_("Use selected location")))
        self.use_place.Bind(wx.EVT_BUTTON, self.on_use_place)
        self.lookup_status = helper.addLabeledControl(
            _("Location lookup status"),
            wx.TextCtrl,
            value=_("Search is only sent when you activate Search. No location is selected automatically."),
            style=wx.TE_READONLY,
        )
        self.use_place.Enable(False)
        self.place_choices.Enable(False)
        self.lat_ctrl = helper.addLabeledControl(_("Latitude"), wx.TextCtrl, value=values["lat"])
        self.lon_ctrl = helper.addLabeledControl(_("Longitude"), wx.TextCtrl, value=values["lon"])
        try:
            if values["location_name"]:
                self._chosen_location = Location(
                    coordinate(values["lat"]),
                    coordinate(values["lon"], latitude=False),
                    values["location_name"],
                )
        except PrayerError:
            pass
        self.lat_ctrl.Bind(wx.EVT_TEXT, self.on_coordinates_changed)
        self.lon_ctrl.Bind(wx.EVT_TEXT, self.on_coordinates_changed)
        self._location_ready = True
        self.on_toggle_auto(None)

    def _manual_location(self):
        location = Location(coordinate(self.lat_ctrl.GetValue()), coordinate(self.lon_ctrl.GetValue(), False))
        if self._chosen_location and self._chosen_location.coordinates == location.coordinates:
            return self._chosen_location
        self._chosen_location = None
        return location

    def _render_location(self):
        auto = self.auto_detect.GetValue()
        if auto:
            text = (
                handler.location_text(self._automatic_location, True)
                if self._automatic_location
                else _("Automatic location is not available yet. Activate Refresh automatic location.")
            )
        else:
            try:
                text = handler.location_text(self._manual_location(), False)
            except PrayerError:
                text = _("Enter valid coordinates or search for your location.")
        self.location_summary.SetValue(text)

    def on_toggle_auto(self, event):
        auto = self.auto_detect.GetValue()
        self.lat_ctrl.Enable(not auto)
        self.lon_ctrl.Enable(not auto)
        if not getattr(self, "_location_ready", False):
            return
        self._render_location()
        self.refresh_location.Enable(auto and not self._lookup_busy)
        if auto and self._automatic_location is None and not self._lookup_busy:
            self._begin_lookup("auto")

    def on_coordinates_changed(self, event):
        if self._location_ready:
            self._render_location()
        event.Skip()

    def on_refresh_location(self, event):
        if self.auto_detect.GetValue() and not self._lookup_busy:
            self._begin_lookup("auto")

    def on_search_query_changed(self, event):
        self._places = ()
        self.place_choices.Clear()
        self.place_choices.Enable(False)
        self.use_place.Enable(False)
        if not self._lookup_busy:
            self.lookup_status.SetValue(
                _("Search is only sent when you activate Search. No location is selected automatically.")
            )
        event.Skip()

    def on_search_location(self, event):
        if self._lookup_busy:
            return
        query = self.search_query.GetValue().strip()
        if not 2 <= len(query) <= 200:
            self._lookup_message(handler.lookup_error("search_query"))
            self.search_query.SetFocus()
            return
        self._places = ()
        self.place_choices.Clear()
        self.place_choices.Enable(False)
        self.use_place.Enable(False)
        self._begin_lookup("search", query)

    def _begin_lookup(self, kind, query=""):
        if self._lookup_closed or self._lookup_busy:
            return
        self._lookup_id += 1
        ticket = self._lookup_id
        self._lookup_busy = True
        self.search_button.Enable(False)
        self.refresh_location.Enable(False)
        self._lookup_message(
            _("Detecting approximate IP location...") if kind == "auto" else _("Searching locations...")
        )
        # Capture NVDA language on the GUI thread.
        language = languageHandler.getLanguage()
        threading.Thread(
            target=self._lookup_worker,
            args=(ticket, kind, query, language),
            name="prayerTimesLocation",
            daemon=True,
        ).start()

    def _lookup_worker(self, ticket, kind, query, language):
        result, error = None, None
        try:
            if kind == "auto":
                self._location_service.invalidate()
                result = self._location_service.get_location()
            else:
                result = search_locations(query, language)
        except StaleRequest:
            return
        except PrayerError as exc:
            error = exc.code
        except Exception:
            error = "unexpected"
        wx.CallAfter(self._finish_lookup, ticket, kind, query, result, error)

    def _lookup_message(self, text):
        self.lookup_status.SetValue(text)
        if self.IsShownOnScreen():
            ui.message(text)

    def _finish_lookup(self, ticket, kind, query, result, error):
        if not self or self.IsBeingDeleted() or self._lookup_closed:
            return
        self._lookup_busy = False
        self.search_button.Enable(True)
        self.refresh_location.Enable(self.auto_detect.GetValue())
        if ticket != self._lookup_id:
            return
        if kind == "search" and query != self.search_query.GetValue().strip():
            self._lookup_message(
                _("Search is only sent when you activate Search. No location is selected automatically.")
            )
            return
        if error:
            self._lookup_message(handler.lookup_error(error))
        elif kind == "auto":
            self._automatic_location = result
            self._render_location()
            if self.auto_detect.GetValue():
                self._lookup_message(
                    handler.location_text(result, True)
                    + " "
                    + _("If this location is wrong, search below and use the correct match.")
                )
        elif query == self.search_query.GetValue().strip():
            self._places = result
            self.place_choices.SetItems([handler.place_text(place) for place in result])
            self.place_choices.SetSelection(wx.NOT_FOUND)
            self.place_choices.Enable(bool(result))
            self.use_place.Enable(False)
            self._lookup_message(
                _("Found {count} locations. Choose a match and activate Use selected location.").format(
                    count=len(result)
                )
                if result
                else _("No matching locations. Try another spelling, add a country, or enter coordinates.")
            )

    def on_place_selected(self, event):
        index = self.place_choices.GetSelection()
        self.use_place.Enable(0 <= index < len(self._places))

    def on_use_place(self, event):
        index = self.place_choices.GetSelection()
        if not 0 <= index < len(self._places):
            return
        location = self._places[index]
        self.auto_detect.SetValue(False)
        self.lat_ctrl.SetValue(str(location.latitude))
        self.lon_ctrl.SetValue(str(location.longitude))
        self._chosen_location = location
        self.on_toggle_auto(None)
        self._lookup_message(
            _("Selected {place}. Automatic location is off. Activate Apply or OK to save.").format(
                place=location.name
            )
        )
        self.location_summary.SetFocus()

    def location_name_to_save(self):
        if self.auto_detect.GetValue():
            # Keep a previously selected manual place for a later manual switch.
            try:
                return self._manual_location().name if self._chosen_location else ""
            except PrayerError:
                return ""
        return self._manual_location().name

    def onDiscard(self):
        self._lookup_closed = True
        self._lookup_id += 1
        self._location_service.invalidate(close=True)
