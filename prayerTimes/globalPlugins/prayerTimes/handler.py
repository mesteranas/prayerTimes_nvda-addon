"""Translate and format structured prayer data at the presentation boundary."""

from datetime import timedelta

import addonHandler

addonHandler.initTranslation()


def methods():
    return (
        (-1, _("Automatic (based on location)")),
        (13, _("Turkish Presidency of Religious Affairs (Diyanet, experimental)")),
        (3, _("Muslim World League")),
        (5, _("Egyptian General Authority of Survey")),
        (4, _("Umm Al-Qura University, Makkah")),
        (0, _("Shia Ithna-Ashari, Leva Institute, Qum")),
        (1, _("University of Islamic Sciences, Karachi")),
        (2, _("Islamic Society of North America (ISNA)")),
        (7, _("Institute of Geophysics, University of Tehran")),
        (8, _("Gulf Region")),
        (9, _("Kuwait")),
        (10, _("Qatar")),
        (11, _("Majlis Ugama Islam Singapura, Singapore")),
        (12, _("Union Organization Islamic de France")),
        (14, _("Spiritual Administration of Muslims of Russia")),
        (15, _("Moonsighting Committee Worldwide")),
        (16, _("Dubai (experimental)")),
        (17, _("Jabatan Kemajuan Islam Malaysia (JAKIM)")),
        (18, _("Tunisia")),
        (19, _("Algeria")),
        (20, _("Kementerian Agama Republik Indonesia")),
        (21, _("Morocco")),
        (22, _("Comunidade Islamica de Lisboa")),
        (23, _("Ministry of Awqaf, Islamic Affairs and Holy Places, Jordan")),
    )


def prayer_name(key):
    return {
        "Fajr": _("Fajr"),
        "Sunrise": _("Sunrise"),
        "Dhuhr": _("Dhuhr"),
        "Asr": _("Asr"),
        "Maghrib": _("Maghrib"),
        "Isha": _("Isha"),
    }[key]


def format_time(instant, use_24h):
    return instant.strftime("%H:%M" if use_24h else "%I:%M %p")


def place_text(location, include_coordinates=True):
    if location.name and not include_coordinates:
        return location.name
    coords = "{:.4f}, {:.4f}".format(location.latitude, location.longitude)
    return "{} ({})".format(location.name, coords) if location.name else coords


def location_text(location, automatic, include_coordinates=True):
    template = (
        _("Automatic location (approximate): {place}") if automatic else _("Selected location: {place}")
    )
    return template.format(place=place_text(location, include_coordinates))


def lookup_error(code):
    return {
        "search_query": _("Enter a place name or postal code with 2 to 200 characters."),
        "timeout": _("The location lookup timed out. Try again or enter coordinates."),
        "network": _("Location lookup failed. Check your internet connection or enter coordinates."),
    }.get(code, _("Location lookup returned no usable data. Try again or enter coordinates."))


def current_text(data, options, now):
    schedule = data.current(now)
    if schedule is None:
        return None
    lines = [
        _("Date: {date}").format(date=schedule.day.isoformat()),
        _("Time zone: {zone}").format(zone=schedule.timezone_name),
        _("Calculation method: {method}").format(method=dict(methods())[schedule.method]),
        "",
    ]
    if data.location is not None:
        lines.insert(1, location_text(data.location, options.auto_detect))
    for prayer in schedule.prayers:
        value = format_time(prayer.when, options.use_24h)
        if prayer.when.date() > schedule.day:
            value = _("Tomorrow, {time}").format(time=value)
        lines.append("{}: {}".format(prayer_name(prayer.key), value))
    return "\n".join(lines)


def next_text(data, options, now):
    candidate = data.next_prayer(now)
    if candidate is None:
        return None
    schedule, prayer = candidate
    text = "{}: {}".format(prayer_name(prayer.key), format_time(prayer.when, options.use_24h))
    if prayer.when.date() == now.astimezone(schedule.zone).date() + timedelta(days=1):
        text = _("Tomorrow, {prayer}").format(prayer=text)
    result = _("{prayer}. Time zone: {zone}").format(prayer=text, zone=schedule.timezone_name)
    if data.location is not None:
        result += ". " + location_text(data.location, options.auto_detect, include_coordinates=False)
    return result


def error_message(code):
    return {
        "latitude": _("Enter a latitude between -90 and 90."),
        "longitude": _("Enter a longitude between -180 and 180."),
        "settings": _("Check the prayer calculation settings."),
        "timeout": _("The request timed out. Try again."),
        "network": _("Prayer times could not be retrieved. Check your internet connection and try again."),
        "response": _(
            "The prayer service returned invalid or unavailable times. Try another calculation method or location."
        ),
        "location": _("Your location could not be detected. Try again or enter coordinates in settings."),
        "timezone": _("The location's time zone is not supported by this version of the add-on."),
        "date_changed": _("The date changed while retrieving prayer times. Try again."),
    }.get(code, _("Prayer times could not be retrieved. Try again."))
