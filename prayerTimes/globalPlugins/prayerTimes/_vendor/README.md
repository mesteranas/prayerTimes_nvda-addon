# Time zone support

The add-on uses its own TZif files and CPython's pure Python ZoneInfo reader.
This avoids requiring an unbundled `zoneinfo` extension or an installed IANA
database inside frozen NVDA on Windows. No global import paths are modified.

- `_zoneinfo.py` and `_common.py`: adapted CPython 3.13.7 standard-library
  files, https://github.com/python/cpython/tree/v3.13.7/Lib/zoneinfo .
  Local changes replace three assignment expressions and `zip(strict=True)`
  with Python 3.7-compatible equivalents, remove two positional-only parameter
  markers, and reject a truncated TZif footer
  instead of allowing the upstream loop to spin at EOF. Time zone conversion
  algorithms are unchanged. Upstream source hashes are recorded.
- `zoneinfo/__init__.py` and `zoneinfo/_tzpath.py`: local adapter; callers use
  `ZoneInfo.from_file` with explicit packaged data. OS/Python package discovery
  is deliberately unavailable on this path.
- `timezones.zip`: only TZif data files from the PSF tzdata wheel, without
  executing or redistributing its Python package code. IANA tz database data is
  public domain: https://www.iana.org/time-zones . The wheel's accompanying
  license notices are retained alongside CPython's license.
- `versions.json`: precise data version, wheel hash, reader version.

Updates are a deliberate development step, never an automatic network download
at add-on startup. Download a tzdata wheel from PyPI, verify its published SHA256,
then run `python tools/vendor_timezones.py WHEEL SHA256` under the intended
CPython reader version. Run tests, including loading every packaged zone and
DST/fold scenarios, before rebuilding the add-on.
