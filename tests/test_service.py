from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import threading
from pathlib import Path

import pytest


def payload(day="18-10-2026", zone="Europe/Istanbul", method=13, iso=False):
    times = {
        "Fajr": "05:47",
        "Sunrise": "07:12",
        "Dhuhr": "12:54",
        "Asr": "15:56",
        "Maghrib": "18:26",
        "Isha": "19:46",
    }
    if iso:
        prefix = datetime.strptime(day, "%d-%m-%Y").date().isoformat()
        times = {key: prefix + "T" + value + ":00+03:00" for key, value in times.items()}
    return {
        "code": 200,
        "data": {
            "timings": times,
            "date": {"gregorian": {"date": day}},
            "meta": {"timezone": zone, "method": {"id": method}},
        },
    }


def parse(svc, monkeypatch, raw=None, **kwargs):
    monkeypatch.setattr(svc, "_get_json", lambda *args: raw or payload(**kwargs))
    return svc.fetch_schedule(41.0, 29.0, date(2026, 10, 18), svc.Options(method=13))


@pytest.mark.parametrize(
    "value,latitude",
    [
        ("", True),
        ("nan", True),
        ("inf", False),
        ("-inf", True),
        ("90.1", True),
        ("181", False),
        (True, True),
        ("41,0.1", True),
    ],
)
def test_reject_invalid_coordinate(svc, value, latitude):
    with pytest.raises(svc.PrayerError):
        svc.coordinate(value, latitude)


@pytest.mark.parametrize(
    "value,latitude,result",
    [
        ("41,0082", True, 41.0082),
        ("-90", True, -90),
        ("180", False, 180),
        ("0", True, 0),
        (" 29.1 ", False, 29.1),
    ],
)
def test_valid_coordinates(svc, value, latitude, result):
    assert svc.coordinate(value, latitude) == result


@pytest.mark.parametrize("iso", [False, True])
def test_parse_aware_schedule(svc, monkeypatch, iso):
    result = parse(svc, monkeypatch, iso=iso)
    assert result.day == date(2026, 10, 18)
    assert result.prayers[0].when.astimezone(svc.UTC).hour == 2
    assert result.method == 13


def test_suffix_and_separate_imsak_not_used(svc, monkeypatch):
    raw = payload()
    raw["data"]["timings"]["Fajr"] = "05:47 (+03)"
    raw["data"]["timings"]["Imsak"] = "05:37"
    assert parse(svc, monkeypatch, raw).prayers[0].when.minute == 47


@pytest.mark.parametrize(
    "fault",
    [
        "missing_prayer",
        "bad_time",
        "wrong_day",
        "wrong_method",
        "bad_offset",
        "missing_offset",
        "bad_order",
        "error_code",
    ],
)
def test_reject_invalid_responses(svc, monkeypatch, fault):
    raw = payload(iso=True)
    if fault == "missing_prayer":
        del raw["data"]["timings"]["Asr"]
    elif fault == "bad_time":
        raw["data"]["timings"]["Asr"] = "--:--"
    elif fault == "wrong_day":
        raw["data"]["date"]["gregorian"]["date"] = "19-10-2026"
    elif fault == "wrong_method":
        raw["data"]["meta"]["method"]["id"] = 5
    elif fault == "bad_offset":
        raw["data"]["timings"]["Fajr"] = "2026-10-18T05:47:00+02:00"
    elif fault == "missing_offset":
        raw["data"]["timings"]["Fajr"] = "2026-10-18T05:47:00"
    elif fault == "bad_order":
        raw["data"]["timings"]["Asr"] = "2026-10-18T10:00:00+03:00"
    elif fault == "error_code":
        raw["code"] = 400
    with pytest.raises(svc.PrayerError, match="response"):
        parse(svc, monkeypatch, raw)


def test_unknown_timezone_fails_explicitly(svc, monkeypatch):
    with pytest.raises(svc.PrayerError, match="timezone"):
        parse(svc, monkeypatch, zone="Unknown/Region")


@pytest.mark.parametrize("method", [-1, 0, 3, 5, 13, 23])
def test_method_ids_and_school_sent_to_api(svc, monkeypatch, method):
    calls = []
    raw = payload(method=3 if method == -1 else method)

    def get(url, params):
        calls.append((url, params))
        return raw

    monkeypatch.setattr(svc, "_get_json", get)
    svc.fetch_schedule(
        41, 29, date(2026, 10, 18), svc.Options(method=method, school=1, latitude_adjustment=2)
    )
    url, params = calls[0]
    assert url.startswith("https://") and url.endswith("18-10-2026")
    assert ("method" in params) == (method != -1)
    if method != -1:
        assert params["method"] == method
    assert params["school"] == 1 and params["latitudeAdjustmentMethod"] == 2


@pytest.mark.parametrize("failure,code", [("timeout", "timeout"), ("http", "network"), ("json", "response")])
def test_network_failures_and_timeout(svc, monkeypatch, failure, code):
    def get(url, **kwargs):
        assert kwargs["timeout"] == (5, 12)
        if failure == "timeout":
            raise svc.requests.Timeout("sensitive URL should not escape")
        if failure == "http":
            raise svc.requests.HTTPError("sensitive URL should not escape")

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                raise svc.requests.exceptions.JSONDecodeError("invalid JSON", "", 0)

        return Response()

    monkeypatch.setattr(svc.requests, "get", get)
    with pytest.raises(svc.PrayerError) as error:
        svc._get_json("https://example.invalid")
    assert str(error.value) == code


def test_https_location(svc, monkeypatch):
    def get(url, params):
        assert url == "https://ipwho.is/"
        return {"success": True, "latitude": 41.0, "longitude": 29.0}

    monkeypatch.setattr(svc, "_get_json", get)
    assert svc.detect_location() == (41.0, 29.0)


def make_service(
    svc, zone_name="Europe/Istanbul", now="2026-10-18T09:00:00+00:00", fetch_hook=None, locator=None
):
    clock = [datetime.fromisoformat(now)]
    calls = []
    zone = svc.load_timezone(zone_name)

    def fetch(lat, lon, day, options):
        calls.append((lat, lon, day, options))
        if fetch_hook:
            fetch_hook(day)
        times = [(5, 47), (7, 12), (12, 54), (15, 56), (18, 26), (19, 46)]
        prayers = tuple(
            svc.Prayer(key, datetime.combine(day, datetime.min.time(), zone).replace(hour=h, minute=m))
            for key, (h, m) in zip(svc.PRAYER_KEYS, times)
        )
        return svc.Schedule(day, zone_name, zone, 13 if options.method == -1 else options.method, prayers)

    service = svc.PrayerService(clock=lambda: clock[0], fetcher=fetch, locator=locator)
    return service, clock, calls


def test_sunrise_excluded_and_tomorrow_actual_date(svc):
    service, clock, _ = make_service(svc, now="2026-10-18T03:00:00+00:00")
    data = service.get_data(svc.Options(auto_detect=False), True)
    assert data.next_prayer(clock[0])[1].key == "Dhuhr"
    clock[0] = datetime.fromisoformat("2026-10-18T19:00:00+00:00")
    data = service.get_data(svc.Options(auto_detect=False), True)
    candidate = data.next_prayer(clock[0])[1]
    assert candidate.key == "Fajr" and candidate.when.date() == date(2026, 10, 19)


def test_cache_date_options_and_display_format(svc):
    service, clock, calls = make_service(svc)
    options = svc.Options(auto_detect=False, method=13)
    service.get_data(options)
    service.get_data(replace(options, use_24h=False))
    assert len(calls) == 1
    service.get_data(replace(options, school=1))
    service.get_data(replace(options, method=5))
    service.get_data(replace(options, latitude_adjustment=1))
    service.get_data(replace(options, latitude=51))
    assert len(calls) == 5
    clock[0] += timedelta(days=1)
    assert service.get_data(options).today.day == date(2026, 10, 19)
    assert len(calls) == 6 and len(service._cache) <= 4


@pytest.mark.parametrize(
    "zone,now,day",
    [
        ("America/Los_Angeles", "2026-10-18T02:00:00+00:00", date(2026, 10, 17)),
        ("Pacific/Kiritimati", "2026-10-18T15:00:00+00:00", date(2026, 10, 19)),
    ],
)
def test_coordinate_day_not_device_or_utc_day(svc, zone, now, day):
    service, _, calls = make_service(svc, zone, now)
    assert service.get_data(svc.Options(auto_detect=False)).today.day == day
    assert len(calls) == 2


def test_midnight_during_fetch_rechecks_date(svc):
    def cross_midnight(day):
        clock[0] = datetime.fromisoformat("2026-10-18T21:00:01+00:00")

    service, clock, calls = make_service(svc, now="2026-10-18T20:59:59+00:00", fetch_hook=cross_midnight)
    assert service.get_data(svc.Options(auto_detect=False)).today.day == date(2026, 10, 19)
    assert len(calls) == 2


def test_invalidation_during_io_discards_old_result(svc):
    entered, release = threading.Event(), threading.Event()

    def wait(day):
        entered.set()
        assert release.wait(2)

    service, _, _ = make_service(svc, fetch_hook=wait)
    errors = []

    def run():
        try:
            service.get_data(svc.Options(auto_detect=False))
        except svc.StaleRequest:
            errors.append("stale")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert entered.wait(2)
    service.invalidate()
    release.set()
    thread.join(2)
    assert not thread.is_alive() and errors == ["stale"] and not service._cache


def test_location_refresh_after_one_hour(svc):
    locations = []

    def locate():
        locations.append(True)
        return 41, 29

    service, clock, _ = make_service(svc, locator=locate)
    service.get_data(svc.Options())
    service.get_data(svc.Options())
    assert len(locations) == 1
    clock[0] += timedelta(hours=1)
    service.get_data(svc.Options())
    assert len(locations) == 2


def test_closed_service_does_not_fetch(svc):
    service, _, calls = make_service(svc)
    service.invalidate(close=True)
    with pytest.raises(svc.StaleRequest):
        service.get_data(svc.Options(auto_detect=False))
    assert not calls


def test_packaged_timezone_reader_dst_fold_and_future(svc):
    zone = svc.load_timezone("America/New_York")
    before = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc).astimezone(zone)
    after = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).astimezone(zone)
    assert before.hour == after.hour == 1 and before.fold == 0 and after.fold == 1
    assert before.utcoffset() != after.utcoffset()
    assert datetime(2045, 7, 1, tzinfo=zone).utcoffset() == timedelta(hours=-4)


@pytest.mark.parametrize("source", sorted((Path(__file__).parent / "fixtures").glob("smoke_*.json")))
def test_saved_public_provider_responses(svc, monkeypatch, source):
    import json

    raw = json.loads(source.read_text(encoding="utf-8"))
    monkeypatch.setattr(svc, "_get_json", lambda *args: raw)
    day = datetime.strptime(raw["data"]["date"]["gregorian"]["date"], "%d-%m-%Y").date()
    schedule = svc.fetch_schedule(0, 0, day, svc.Options())
    assert schedule.timezone_name == raw["data"]["meta"]["timezone"]
    assert len(schedule.prayers) == 6
    if "oslo" in source.name:
        assert schedule.prayers[-1].when.date() == day + timedelta(days=1)


def test_packaged_reader_matches_standard_library_using_same_data(svc):
    from io import BytesIO
    from zoneinfo import ZoneInfo
    from zipfile import ZipFile

    dates = [
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2060, 11, 1, tzinfo=timezone.utc),
    ]
    with ZipFile(Path(svc.__file__).parent / "_vendor/timezones.zip") as archive:
        for name in archive.namelist():
            reference = ZoneInfo.from_file(BytesIO(archive.read(name)), key=name)
            actual = svc.load_timezone(name)
            for instant in dates:
                left, right = instant.astimezone(reference), instant.astimezone(actual)
                assert (left.isoformat(), left.fold) == (right.isoformat(), right.fold), name


def test_utc_comparison_during_repeated_hour(svc):
    zone = svc.load_timezone("America/New_York")
    # Same wall-clock hour, later real instant. A wall-time comparison would skip it.
    prayer = svc.Prayer("Fajr", datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1))
    schedule = svc.Schedule(date(2026, 11, 1), "America/New_York", zone, 3, (prayer,))
    data = svc.PrayerData(schedule)
    assert data.next_prayer(datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0))[1] == prayer


def test_previous_days_isha_after_midnight_is_not_skipped(svc):
    zone = svc.load_timezone("Europe/Oslo")
    today = svc.Schedule(
        date(2026, 6, 22),
        "Europe/Oslo",
        zone,
        3,
        (svc.Prayer("Fajr", datetime(2026, 6, 22, 2, 21, tzinfo=zone)),),
    )
    previous = svc.Schedule(
        date(2026, 6, 21),
        "Europe/Oslo",
        zone,
        3,
        (svc.Prayer("Isha", datetime(2026, 6, 22, 0, 12, tzinfo=zone)),),
    )
    data = svc.PrayerData(today, previous=previous)
    assert data.next_prayer(datetime(2026, 6, 22, 0, 5, tzinfo=zone))[1].key == "Isha"


def test_isha_iso_wrap_is_normalized(svc, monkeypatch):
    raw = payload(iso=True)
    raw["data"]["timings"]["Isha"] = "2026-10-18T00:12:00+03:00"
    result = parse(svc, monkeypatch, raw)
    assert result.prayers[-1].when.date() == date(2026, 10, 19)


def test_every_packaged_timezone_can_be_loaded(svc):
    from pathlib import Path
    from zipfile import ZipFile

    with ZipFile(Path(svc.__file__).parent / "_vendor/timezones.zip") as archive:
        names = archive.namelist()
        assert len(names) > 500
        for name in names:
            assert svc.load_timezone(name) is not None


def test_runtime_python37_syntax_and_strict_header_compatibility(svc):
    import ast
    from pathlib import Path
    from prayer_test._vendor.zoneinfo._common import _TZifHeader

    for path in Path(svc.__file__).parent.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 7))
    with pytest.raises(ValueError):
        _TZifHeader(1, 2)


def test_truncated_tzif_footer_is_rejected(svc):
    import subprocess
    import sys

    # A regression used to spin at EOF; bound the probe independently of pytest.
    code = """
import importlib.util, io, pathlib, sys, zipfile
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("tz_common", root / "_vendor/zoneinfo/_common.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with zipfile.ZipFile(root / "_vendor/timezones.zip") as archive:
    raw = archive.read("Europe/Istanbul")
assert raw.endswith(b"\\n")
try:
    module.load_data(io.BytesIO(raw[:-1]))
except ValueError as error:
    assert "Truncated" in str(error)
else:
    raise AssertionError("truncated footer accepted")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(Path(svc.__file__).parent)],
        timeout=5,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_service_fetches_previous_isha_and_only_needed_adjacent_days(svc):
    service, clock, calls = make_service(svc, zone_name="Europe/Oslo", now="2026-06-21T22:05:00+00:00")
    original = service._fetcher

    def fetch(*args):
        schedule = original(*args)
        isha = svc.Prayer(
            "Isha",
            datetime.combine(schedule.day + timedelta(days=1), datetime.min.time(), schedule.zone).replace(
                minute=12
            ),
        )
        return replace(schedule, prayers=schedule.prayers[:-1] + (isha,))

    service._fetcher = fetch
    data = service.get_data(svc.Options(auto_detect=False), for_next=True)
    assert data.next_prayer(clock[0])[1].key == "Isha"
    assert data.tomorrow is None and data.previous.day == date(2026, 6, 21)
    clock[0] = datetime.fromisoformat("2026-06-22T10:00:00+00:00")
    count = len(calls)
    data = service.get_data(svc.Options(auto_detect=False), for_next=True)
    assert len(calls) == count and data.next_prayer(clock[0])[1].key == "Dhuhr"
