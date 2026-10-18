# Prayer Times

An NVDA add-on for Islamic prayer times, with manual or IP-based location,
selectable calculation methods and 12/24-hour display.

This checkout contains **2.1.0-dev3**, a local development version. It is not a
published release and has not completed live NVDA acceptance testing.

## Use

- **NVDA+Alt+P:** today's prayer times in a readable, read-only text dialog.
- **NVDA+Shift+P:** the next prayer; sunrise is excluded. After Isha, tomorrow's
  actual Fajr is used. Isha after midnight is handled as part of the previous
  calculation day when appropriate.
- **Escape** or **Close:** dismiss the result dialog.
- Configure the shortcuts in NVDA's Input Gestures dialog.

In NVDA Settings, open **prayer times**. Automatic location uses the public IP
address, not GPS. VPNs and mobile networks can locate you incorrectly. Disable
it and enter latitude/longitude for a precise location. Decimal dots and commas
are accepted; blank, non-finite and out-of-range coordinates are rejected.

The settings panel displays the detected city/region/country and coordinates,
marked as an **approximate IP location**. You can refresh this preview. Prayer
results identify the location actually used; the next-prayer announcement also
includes its name. If a provider supplies no name, coordinates remain visible.

If detection is wrong, enter a city, district or postal code and activate
**Search for a location**. For example, `Ankara, TR`, `Çankaya, TR` or `Paris,
France`. A two-letter suffix after the last comma is treated as an explicit
country code; use full names for regions. Up to ten matches show their country,
region and coordinates. Choose one, then activate **Use selected location**.
This fills the coordinates and switches automatic detection off. Activate
**Apply** or **OK** to save. The first match is never applied automatically.
Changing coordinates manually removes the selected place name if they differ.
Cancel leaves the saved location unchanged. Settings previews and unconfirmed
search results do not change the active prayer location.

Search is sent only when its button is activated, not on each keystroke. It uses
[Open-Meteo geocoding](https://open-meteo.com/en/docs/geocoding-api), with location
data by [GeoNames](https://www.geonames.org/) under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The query and client IP
are visible to that service. Its free endpoint is for non-commercial use and
has service limits; see its [terms](https://open-meteo.com/en/terms). If a place
is absent or lookup is unavailable, manual coordinates remain available.
Place coordinates represent the indexed location, not a GPS fix or an official
prayer authority's timetable location. Check the calculation method separately.

## Calculation choices

All 23 named methods currently supported by Aladhan are selectable, including
Diyanet, MWL, ISNA, Egyptian, Umm al-Qura, Karachi, Singapore, JAKIM and Kemenag.
There are also Standard/Hanafi Asr and three high-latitude adjustment options.

New configurations default to **Automatic (based on location)**. The service's
geographically nearest method is a starting point, not proof of agreement with
your local authority. Choose the method recommended locally. For example, the
provider may select Kemenag for Sydney or Morocco for São Paulo. The result
identifies the method actually used and the location's time zone. Upgrades from
V2.0 retain its Egyptian method (5) until changed in settings.

Aladhan labels Diyanet (13) and Dubai (16) experimental. Diyanet mode is not a
direct download of the official Diyanet timetable. Minute differences can
remain. At polar latitudes, some dates may not have sunrise/sunset; unavailable
provider results produce a clear error rather than invented times.

Times are calculated for the coordinate time zone, including daylight-saving
changes, independently of the computer's zone. The add-on includes IANA time
zone data, so users need no extra Python installation.

## Network and cache

Prayer data comes from **https://api.aladhan.com**. Automatic location uses
**https://ipwho.is**, which receives your public IP address. Aladhan receives
the chosen coordinates and calculation settings. Manual mode does not contact
the location provider. No automatic HTTP downgrade or alternate-provider
fallback is used. These are external services; network availability and free
service limits apply.

Daily schedules are cached in memory by date, coordinates, method, Asr school
and high-latitude setting. The date is rechecked on every shortcut. The next
prayer command obtains tomorrow's schedule when needed and, before Fajr, the previous day
to account for Isha after midnight. IP location is refreshed after one hour.
Save/Apply settings or restart NVDA to clear the cache immediately. Requests
have connection/read timeouts; repeated commands share one active worker.
Outdated results cannot refill the cache after settings are saved.

## Development

```powershell
python -m pip install -r requirements-dev.txt
python -B -m pytest -q
python -m ruff check prayerTimes tests tools
python -B tools/build_addon.py
```

The package is produced in `dist/`. Tests use controlled NVDA/wx boundaries;
they do not require an installed/running NVDA. They cover dates, time zones,
cache invalidation, request lifecycle, translation and reproducible packaging.
They do not replace live screen-reader, focus or braille acceptance tests.

After editing translatable strings, run `python tools/update_locales.py`, update
the PO translations and rebuild. Turkish catalogs must be complete; other
languages retain their existing translations and fall back to English for
untranslated additions. Existing source contributor metadata is retained.

`tools/build_addon.py` verifies translations/placeholders and compiles catalogs
for the ZIP without including tests, development tools or bytecode. With the
same sources it produces identical bytes. Runtime time zone versions and
licenses are documented in `prayerTimes/globalPlugins/prayerTimes/_vendor/`.

## Languages and license

English, Turkish, Arabic and German. Turkish and English help documents cover
all current options; Arabic and German help includes the updated essentials.

The add-on is GPL-2.0. Bundled CPython reader and time zone data retain their
own notices. Contributions are welcome through the
[upstream repository](https://github.com/mesteranas/prayerTimes_nvda-addon).
