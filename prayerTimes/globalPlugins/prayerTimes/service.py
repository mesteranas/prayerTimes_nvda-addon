"""Prayer data and cache, independent of NVDA and translated display strings."""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO
import math
from pathlib import Path
import threading
from zipfile import ZipFile

import requests

from ._vendor.zoneinfo import ZoneInfo

UTC = timezone.utc
TIMEOUT = (5, 12)
PRAYER_KEYS = ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")
METHOD_IDS = (-1, 0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)


class PrayerError(Exception):
    """A stable, non-sensitive code for translation by the UI."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class StaleRequest(Exception):
    """An invalidated request must not populate the cache or reach the UI."""


def coordinate(value, latitude=True):
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(str(value).strip().replace(",", "."))
        limit = 90 if latitude else 180
        if not math.isfinite(number) or not -limit <= number <= limit:
            raise ValueError
        return number
    except (ValueError, TypeError):
        raise PrayerError("latitude" if latitude else "longitude") from None


@dataclass(frozen=True)
class Options:
    auto_detect: bool = True
    latitude: float = 0.0
    longitude: float = 0.0
    method: int = -1
    school: int = 0
    latitude_adjustment: int = 3
    use_24h: bool = True
    location_name: str = ""

    def __post_init__(self):
        if (
            self.method not in METHOD_IDS
            or self.school not in (0, 1)
            or self.latitude_adjustment not in (1, 2, 3)
        ):
            raise PrayerError("settings")
        if not self.auto_detect:
            coordinate(self.latitude)
            coordinate(self.longitude, latitude=False)


@dataclass(frozen=True)
class Prayer:
    key: str
    when: datetime


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    name: str = ""

    @property
    def coordinates(self):
        return self.latitude, self.longitude


def place_name(*parts):
    # Keep provider text on one line, and avoid duplicate city/region names.
    names = []
    for part in parts:
        if isinstance(part, str):
            text = " ".join(part.split())[:160]
            if text and text.casefold() not in [name.casefold() for name in names]:
                names.append(text)
    return ", ".join(names)


@dataclass(frozen=True)
class Schedule:
    day: date
    timezone_name: str
    zone: object
    method: int
    prayers: tuple


@dataclass(frozen=True)
class PrayerData:
    today: Schedule
    tomorrow: object = None
    previous: object = None
    location: object = None

    def current(self, now):
        target_day = now.astimezone(self.today.zone).date()
        return next((s for s in (self.today, self.tomorrow) if s is not None and s.day == target_day), None)

    def next_prayer(self, now):
        schedule = self.current(now)
        if schedule is None:
            return None
        candidates = [
            (s, prayer)
            for s in (self.previous, self.today, self.tomorrow)
            if s is not None and schedule.day - timedelta(days=1) <= s.day <= schedule.day + timedelta(days=1)
            for prayer in s.prayers
            if prayer.key != "Sunrise" and prayer.when.astimezone(UTC) > now.astimezone(UTC)
        ]
        return min(candidates, key=lambda item: item[1].when.astimezone(UTC), default=None)


@lru_cache(maxsize=32)
def load_timezone(name):
    # Frozen NVDA on Windows need not supply zoneinfo or a system IANA database.
    try:
        if not isinstance(name, str) or not name or ".." in name.split("/") or "\\" in name:
            raise ValueError
        with ZipFile(Path(__file__).parent / "_vendor" / "timezones.zip") as archive:
            return ZoneInfo.from_file(BytesIO(archive.read(name)), key=name)
    except (KeyError, ValueError, OSError):
        raise PrayerError("timezone") from None


def _get_json(url, params=None):
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.Timeout:
        raise PrayerError("timeout") from None
    except requests.RequestException:
        raise PrayerError("network") from None
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, TypeError):
        raise PrayerError("response") from None


def detect_location():
    data = _get_json(
        "https://ipwho.is/", {"fields": "success,latitude,longitude,city,region,country,country_code"}
    )
    if data.get("success") is not True:
        raise PrayerError("location")
    try:
        return Location(
            coordinate(data["latitude"]),
            coordinate(data["longitude"], latitude=False),
            place_name(data.get("city"), data.get("region"), data.get("country"), data.get("country_code")),
        )
    except (KeyError, PrayerError):
        raise PrayerError("location") from None


def search_locations(query, language="en"):
    query = " ".join(query.split())
    if not 2 <= len(query) <= 200:
        raise PrayerError("search_query")
    params = {"name": query, "count": 10, "language": language.split("_")[0].split("-")[0].lower()}
    name, separator, qualifier = query.rpartition(",")
    qualifier = qualifier.strip()
    # An explicit country filter works consistently, including TR and ID.
    # Never retry a failed country search against a different/global location.
    if separator and len(qualifier) == 2 and qualifier.isascii() and qualifier.isalpha():
        if len(name.strip()) < 2:
            raise PrayerError("search_query")
        params["name"] = name.strip()
        params["countryCode"] = qualifier.upper()
    raw = _get_json("https://geocoding-api.open-meteo.com/v1/search", params)
    if raw.get("error") or not isinstance(raw.get("results", []), list):
        raise PrayerError("search_response")
    places = []
    for entry in raw.get("results", [])[:10]:
        try:
            if "countryCode" in params and entry.get("country_code") != params["countryCode"]:
                continue
            if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                raise ValueError
            location = Location(
                coordinate(entry["latitude"]),
                coordinate(entry["longitude"], latitude=False),
                place_name(
                    entry["name"],
                    entry.get("admin2"),
                    entry.get("admin1"),
                    entry.get("country"),
                    entry.get("country_code"),
                ),
            )
        except (AttributeError, KeyError, ValueError, PrayerError):
            continue
        if location not in places:
            places.append(location)
    if raw.get("results") and not places:
        raise PrayerError("search_response")
    return tuple(places)


def fetch_schedule(latitude, longitude, day, options):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "school": options.school,
        "latitudeAdjustmentMethod": options.latitude_adjustment,
        "iso8601": "true",
    }
    if options.method != -1:
        params["method"] = options.method
    raw = _get_json("https://api.aladhan.com/v1/timings/" + day.strftime("%d-%m-%Y"), params)
    try:
        if raw.get("code") != 200:
            raise ValueError
        data = raw["data"]
        actual_day = datetime.strptime(data["date"]["gregorian"]["date"], "%d-%m-%Y").date()
        if actual_day != day:
            raise ValueError
        zone_name = data["meta"]["timezone"]
        zone = load_timezone(zone_name)
        method = int(data["meta"]["method"]["id"])
        if method not in METHOD_IDS or method == -1 or (options.method != -1 and method != options.method):
            raise ValueError
        prayers = []
        for key in PRAYER_KEYS:
            value = data["timings"][key]
            if "T" in value:
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if instant.utcoffset() is None:
                    raise ValueError
                local = instant.astimezone(zone)
                if instant.replace(tzinfo=None) != local.replace(tzinfo=None) or local.date() not in (
                    day,
                    day + timedelta(days=1),
                ):
                    raise ValueError
                if key != "Isha" and local.date() != day:
                    raise ValueError
                # Aladhan may attach the requested date to an Isha clock time
                # after midnight. Normalize that one wrap, in the target zone.
                if (
                    key == "Isha"
                    and local.date() == day
                    and prayers
                    and local.astimezone(UTC) < prayers[-1].when.astimezone(UTC)
                ):
                    local += timedelta(days=1)
            else:
                local = datetime.combine(day, datetime.strptime(value.split()[0], "%H:%M").time(), zone)
                if key == "Isha" and prayers and local.astimezone(UTC) < prayers[-1].when.astimezone(UTC):
                    local += timedelta(days=1)
            if prayers and local.astimezone(UTC) < prayers[-1].when.astimezone(UTC):
                raise ValueError
            prayers.append(Prayer(key, local))
        return Schedule(day, zone_name, zone, method, tuple(prayers))
    except (KeyError, IndexError, ValueError, TypeError, AttributeError, OverflowError):
        raise PrayerError("response") from None


class PrayerService:
    """One network worker; invalidate/close may run on the GUI thread."""

    def __init__(self, clock=None, fetcher=None, locator=None):
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fetcher = fetcher or fetch_schedule
        self._locator = locator or detect_location
        self._lock = threading.Lock()
        self._revision = 0
        self._closed = False
        self._cache = OrderedDict()
        self._zones = {}
        self._location = None

    def invalidate(self, close=False):
        with self._lock:
            self._revision += 1
            self._closed = self._closed or close
            self._cache.clear()
            self._zones.clear()
            self._location = None

    def _check(self, revision):
        if self._closed or revision != self._revision:
            raise StaleRequest

    def _resolve_location(self, options, revision):
        if not options.auto_detect:
            return Location(
                coordinate(options.latitude),
                coordinate(options.longitude, latitude=False),
                options.location_name,
            )
        now = self._clock()
        with self._lock:
            self._check(revision)
            if self._location and timedelta(0) <= now - self._location[0] < timedelta(hours=1):
                return self._location[1]
        location = self._locator()
        location = Location(
            coordinate(location.latitude), coordinate(location.longitude, latitude=False), location.name
        )
        with self._lock:
            self._check(revision)
            self._location = (now, location)
        return location

    def get_location(self, options=None):
        with self._lock:
            revision = self._revision
            self._check(revision)
        return self._resolve_location(options or Options(), revision)

    def cached_location(self):
        with self._lock:
            if self._location and timedelta(0) <= self._clock() - self._location[0] < timedelta(hours=1):
                return self._location[1]
        return None

    def _schedule(self, coords, day, options, revision):
        key = (coords, day, options.method, options.school, options.latitude_adjustment)
        with self._lock:
            self._check(revision)
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        schedule = self._fetcher(*coords, day, options)
        with self._lock:
            self._check(revision)
            self._cache[key] = schedule
            self._zones[coords] = schedule.zone
            if len(self._zones) > 8:
                self._zones = {coords: schedule.zone}
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
        return schedule

    def get_data(self, options, for_next=False):
        with self._lock:
            revision = self._revision
            self._check(revision)
        location = self._resolve_location(options, revision)
        coords = location.coordinates
        with self._lock:
            zone = self._zones.get(coords, UTC)
        for _attempt in range(3):
            day = self._clock().astimezone(zone).date()
            today = self._schedule(coords, day, options, revision)
            zone = today.zone
            # Identify the coordinate time zone, then recheck after network I/O.
            if self._clock().astimezone(zone).date() != day:
                continue
            previous = None
            if for_next and self._clock().astimezone(UTC) < today.prayers[0].when.astimezone(UTC):
                previous = self._schedule(coords, day - timedelta(days=1), options, revision)
            tomorrow = None
            if for_next and PrayerData(today, previous=previous).next_prayer(self._clock()) is None:
                tomorrow = self._schedule(coords, day + timedelta(days=1), options, revision)
            if self._clock().astimezone(zone).date() == day:
                with self._lock:
                    self._check(revision)
                return PrayerData(today, tomorrow, previous, location)
        raise PrayerError("date_changed")
