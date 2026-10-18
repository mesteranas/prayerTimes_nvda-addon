# 2.1.0-dev3 — visible location and place selection

- Show approximate automatic city/region/country and coordinates in settings;
  identify the location used in prayer results and next-prayer announcements.
- Add explicit global city/district/postal-code search via Open-Meteo/GeoNames,
  disambiguated matches and a separate Use selected location action.
- Save manual selection only with Apply/OK; clear a place name after coordinate
  edits and ignore stale or closed-panel lookup results. Lookups run off the GUI thread.

# 2.1.0-dev2 — configuration initialization fix

- Inspect raw profiles before registering defaults, avoiding NVDA's cached
  missing settings/empty schema on startup. This fixes the settings category
  failing to open and commands stopping after the loading announcement.
- Exercise cached section/spec behavior in the configuration test boundary.

# 2.1.0-dev — local development

- Separate prayer identities and aware datetimes from translated display text.
- Correct coordinate-date, next-day Fajr, DST and Isha-after-midnight handling.
- Cache daily schedules by location and calculation settings; reject results
  invalidated by settings changes or plugin termination.
- Use HTTPS, connection/read timeouts and clear errors. Change automatic
  location provider from IP-API to IPWHOIS.IO / ipwho.is.
- Offer all 23 named Aladhan methods, automatic selection, Standard/Hanafi Asr,
  high-latitude adjustments and 12/24-hour display.
- Retain method 5 for V2.0 upgrades; use automatic selection for new settings.
- Validate manual coordinates and associate labels using NVDA's GUI helper.
- Complete Turkish catalog and help; refresh help in English, Arabic and German.
- Bundle portable IANA time zone support, with versions and license notices.
- Add focused tests, reproducible packaging and a CI configuration.

Not published. Live NVDA/focus/braille acceptance is still required. Existing
manifest compatibility limits are retained; they do not claim new live tests.
