from datetime import datetime
import json
from pathlib import Path
import threading
import weakref

import addonHandler

addonHandler.initTranslation()

import config
import globalPluginHandler
import gui
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel, NVDASettingsDialog
from logHandler import log
from scriptHandler import script
import ui
import wx

from . import handler
from .service import Options, PrayerError, PrayerService, StaleRequest, UTC, coordinate

SECTION = "prayerTimes"
# Before registering defaults: upgrading V2.0 must keep its method 5.
_had_settings = SECTION in config.conf
try:
    _legacy_upgrade = json.loads(
        (Path(__file__).parents[2] / "_installation.json").read_text(encoding="utf-8")
    )["preserve_legacy_method"]
except FileNotFoundError:
    _legacy_upgrade = False
except (ValueError, KeyError, OSError):
    _legacy_upgrade = True
config.conf.spec[SECTION] = {
    "auto_detect": "boolean(default=true)",
    "lat": "string(default=0.0)",
    "lon": "string(default=0.0)",
    "method": "integer(default=5)",
    "use_24h": "boolean(default=true)",
    "school": "integer(default=0,min=0,max=1)",
    "latitude_adjustment": "integer(default=3,min=1,max=3)",
}
if not _had_settings and not _legacy_upgrade:
    config.conf[SECTION]["method"] = -1

_instances = weakref.WeakSet()


def read_options():
    values = config.conf[SECTION]
    auto = values["auto_detect"]
    return Options(
        auto_detect=auto,
        latitude=0.0 if auto else coordinate(values["lat"]),
        longitude=0.0 if auto else coordinate(values["lon"], latitude=False),
        method=values["method"],
        school=values["school"],
        latitude_adjustment=values["latitude_adjustment"],
        use_24h=values["use_24h"],
    )


class ResultDialog(wx.Dialog):
    def __init__(self, text, on_closed):
        super().__init__(gui.mainFrame, title=_("Result"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._on_closed = on_closed
        sizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
        self.output = helper.addLabeledControl(
            _("Prayer times"),
            wx.TextCtrl,
            value=text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
            size=(550, 300),
        )
        close = wx.Button(self, wx.ID_CLOSE, label=_("Close"))
        helper.addDialogDismissButtons(close)
        close.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.SetSizerAndFit(sizer)

    def present(self, text=None):
        if text is not None:
            self.output.SetValue(text)
        gui.mainFrame.prePopup()
        try:
            self.Show()
            self.Raise()
        finally:
            gui.mainFrame.postPopup()
        wx.CallAfter(self._focus_output)

    def _focus_output(self):
        if self and not self.IsBeingDeleted():
            self.output.SetInsertionPoint(0)
            self.output.SetFocus()

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _on_close(self, event):
        self._on_closed()
        self.Destroy()


class PrayerSettingsPanel(SettingsPanel):
    title = _("prayer times")

    def makeSettings(self, settingsSizer):
        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        values = config.conf[SECTION]
        self.auto_detect = helper.addItem(
            wx.CheckBox(self, label=_("Detect location automatically. Not accurate in all cases"))
        )
        self.auto_detect.SetValue(values["auto_detect"])
        self.auto_detect.Bind(wx.EVT_CHECKBOX, self.on_toggle_auto)
        self.lat_ctrl = helper.addLabeledControl(_("Latitude"), wx.TextCtrl, value=values["lat"])
        self.lon_ctrl = helper.addLabeledControl(_("Longitude"), wx.TextCtrl, value=values["lon"])
        self._methods = handler.methods()
        self.method = helper.addLabeledControl(
            _("Calculation method"), wx.Choice, choices=[name for _id, name in self._methods]
        )
        ids = [key for key, _name in self._methods]
        self.method.SetSelection(ids.index(values["method"]) if values["method"] in ids else ids.index(5))
        method_hint = wx.StaticText(
            self,
            label=_(
                "Choose the method recommended by your local prayer authority. Automatic selection may differ."
            ),
        )
        method_hint.Wrap(450)
        helper.addItem(method_hint)
        self.school = helper.addLabeledControl(
            _("Asr calculation"),
            wx.Choice,
            choices=[_("Standard (Shafi'i, Maliki, Hanbali)"), _("Hanafi")],
        )
        self.school.SetSelection(values["school"])
        self.latitude_adjustment = helper.addLabeledControl(
            _("High latitude adjustment"),
            wx.Choice,
            choices=[_("Middle of the night"), _("One seventh of the night"), _("Angle based")],
        )
        self.latitude_adjustment.SetSelection(values["latitude_adjustment"] - 1)
        self.use_24h = helper.addItem(wx.CheckBox(self, label=_("Use 24-hour time format")))
        self.use_24h.SetValue(values["use_24h"])
        self.on_toggle_auto(None)

    def on_toggle_auto(self, event):
        enabled = not self.auto_detect.GetValue()
        # The helper also updates the associated label's enabled state.
        self.lat_ctrl.Enable(enabled)
        self.lon_ctrl.Enable(enabled)

    def postInit(self):
        self.auto_detect.SetFocus()

    def isValid(self):
        if not self.auto_detect.GetValue():
            for control, latitude in ((self.lat_ctrl, True), (self.lon_ctrl, False)):
                try:
                    coordinate(control.GetValue(), latitude=latitude)
                except PrayerError as error:
                    gui.messageBox(
                        handler.error_message(error.code),
                        _("Invalid coordinates"),
                        wx.OK | wx.ICON_ERROR,
                        parent=self,
                    )
                    control.SetFocus()
                    return False
        return True

    def onSave(self):
        values = config.conf[SECTION]
        values["auto_detect"] = self.auto_detect.GetValue()
        if not values["auto_detect"]:
            values["lat"] = str(coordinate(self.lat_ctrl.GetValue()))
            values["lon"] = str(coordinate(self.lon_ctrl.GetValue(), latitude=False))
        values["method"] = self._methods[self.method.GetSelection()][0]
        values["school"] = self.school.GetSelection()
        values["latitude_adjustment"] = self.latitude_adjustment.GetSelection() + 1
        values["use_24h"] = self.use_24h.GetValue()
        for instance in list(_instances):
            instance.invalidate()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("prayer times")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = PrayerService()
        self._generation = 0
        self._alive = True
        self._busy = False
        self._pending = set()
        self._active_actions = ()
        self._active_generation = 0
        self._dialog = None
        _instances.add(self)
        if PrayerSettingsPanel not in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.append(PrayerSettingsPanel)

    def invalidate(self):
        self._generation += 1
        self._pending.clear()
        self._service.invalidate()

    def _request(self, action):
        if not self._alive:
            return
        if self._busy and self._active_generation == self._generation and action in self._active_actions:
            return
        self._pending.add(action)
        ui.message(_("loading"))
        self._start_pending()

    def _start_pending(self):
        if self._busy or not self._pending or not self._alive:
            return
        try:
            options = read_options()
        except PrayerError as error:
            self._pending.clear()
            ui.message(handler.error_message(error.code))
            return
        actions = tuple(sorted(self._pending))
        self._pending.clear()
        self._active_actions = actions
        self._active_generation = self._generation
        self._busy = True
        threading.Thread(
            target=self._fetch,
            args=(options, self._generation, actions),
            name="prayerTimes",
            daemon=True,
        ).start()

    def _fetch(self, options, generation, actions):
        data, error = None, None
        try:
            data = self._service.get_data(options, for_next="next" in actions)
        except StaleRequest:
            pass
        except PrayerError as exc:
            error = exc.code
            log.warning("PrayerTimes request failed (%s)", error)
        except Exception:
            error = "unexpected"
            log.exception("Unexpected PrayerTimes failure")
        wx.CallAfter(self._finish, options, generation, actions, data, error)

    def _finish(self, options, generation, actions, data, error):
        if not self._alive:
            return
        self._busy = False
        if generation == self._generation:
            try:
                unchanged = options == read_options()
            except PrayerError:
                unchanged = False
            if not unchanged:
                self._pending.update(actions)
            elif error:
                ui.message(handler.error_message(error))
            elif data is not None:
                now = datetime.now(UTC)
                for action in actions:
                    text = (
                        handler.next_text(data, options, now)
                        if action == "next"
                        else handler.current_text(data, options, now)
                    )
                    if text is None:
                        self._pending.add(action)
                    elif action == "next":
                        ui.message(text)
                    else:
                        self._show_result(text)
        self._start_pending()

    def _show_result(self, text):
        if self._dialog:
            self._dialog.present(text)
        else:
            self._dialog = ResultDialog(text, self._dialog_closed)
            self._dialog.present()

    def _dialog_closed(self):
        self._dialog = None

    @script(gesture="kb:NVDA+alt+p", description=_("Get current prayer times"))
    def script_toggle(self, gesture):
        self._request("current")

    @script(gesture="kb:NVDA+shift+p", description=_("Get next prayer time"))
    def script_toggle1(self, gesture):
        self._request("next")

    def terminate(self):
        self._alive = False
        self._pending.clear()
        self._service.invalidate(close=True)
        _instances.discard(self)
        if self._dialog:
            self._dialog.Destroy()
            self._dialog = None
        if not _instances and PrayerSettingsPanel in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.remove(PrayerSettingsPanel)
        super().terminate()
