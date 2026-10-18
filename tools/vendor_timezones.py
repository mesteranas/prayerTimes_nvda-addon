"""Prepare package-local timezone support; accepts a verified tzdata wheel, never installs it."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def adapt_reader(name, source):
    """Support NVDA 2023's Python 3.7 without new runtime dependencies."""
    replacements = {
        "_zoneinfo.py": [
            ("    def from_file(cls, file_obj, /, key=None):", "    def from_file(cls, file_obj, key=None):"),
            ("    def _unpickle(cls, key, from_cache, /):", "    def _unpickle(cls, key, from_cache):"),
            (
                '    if std_offset := m.group("stdoff"):',
                '    std_offset = m.group("stdoff")\n    if std_offset:',
            ),
            (
                '        if dst_offset := m.group("dstoff"):',
                '        dst_offset = m.group("dstoff")\n        if dst_offset:',
            ),
        ],
        "_common.py": [
            (
                '        while (c := fobj.read(1)) != b"\\n":\n            tz_bytes += c',
                '        c = fobj.read(1)\n        while c != b"\\n":\n            if not c:\n                raise ValueError("Truncated TZif footer")\n            tz_bytes += c\n            c = fobj.read(1)',
            ),
            (
                "        for attr, val in zip(self.__slots__, args, strict=True):",
                '        if len(self.__slots__) != len(args):\n            raise ValueError("Invalid TZif header length")\n        for attr, val in zip(self.__slots__, args):',
            ),
        ],
    }
    for before, after in replacements[name]:
        if source.count(before) != 1:
            raise ValueError("Reader changed upstream; review compatibility adapter")
        source = source.replace(before, after)
    source = "# Adapted for Python 3.7; see ../README.md for changes and license.\n" + source
    ast.parse(source, feature_version=(3, 7))
    return source


def prepare(wheel, expected_hash):
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != expected_hash:
        raise ValueError("tzdata wheel SHA256 mismatch")
    target = Path(__file__).resolve().parents[1] / "prayerTimes/globalPlugins/prayerTimes/_vendor"
    zone = target / "zoneinfo"
    zone.mkdir(parents=True, exist_ok=True)
    target.joinpath("__init__.py").write_text("", encoding="utf-8")
    stdlib = Path(sys.base_prefix) / "Lib/zoneinfo"
    source_hashes = {}
    for name in ("_zoneinfo.py", "_common.py"):
        raw = stdlib.joinpath(name).read_bytes()
        source_hashes[name] = hashlib.sha256(raw).hexdigest()
        zone.joinpath(name).write_text(
            adapt_reader(name, raw.decode("utf-8").replace("\r\n", "\n")), encoding="utf-8"
        )
    zone.joinpath("__init__.py").write_text("from ._zoneinfo import ZoneInfo\n", encoding="utf-8")
    # Its optional OS lookup path is deliberately sealed:
    # production always calls ZoneInfo.from_file on the explicit packaged TZif.
    zone.joinpath("_tzpath.py").write_text(
        '"""Package-local adapter: only ZoneInfo.from_file is supported."""\n'
        "def find_tzfile(key):\n"
        '    raise RuntimeError("Use ZoneInfo.from_file with packaged data")\n',
        encoding="utf-8",
    )
    target.joinpath("LICENSE_PYTHON.txt").write_bytes(Path(sys.base_prefix, "LICENSE.txt").read_bytes())
    with ZipFile(wheel) as source, ZipFile(target / "timezones.zip", "w", ZIP_DEFLATED) as out:
        for name in sorted(source.namelist()):
            value = source.read(name)
            if name.startswith("tzdata/zoneinfo/") and value.startswith(b"TZif"):
                info = ZipInfo(name.removeprefix("tzdata/zoneinfo/"), (2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                out.writestr(info, value)
            if ".dist-info/licenses/" in name and not name.endswith("/"):
                target.joinpath("TZDATA_" + name.rsplit("/", 1)[-1] + ".txt").write_bytes(value)
        metadata = source.read(
            next(n for n in source.namelist() if n.endswith(".dist-info/METADATA"))
        ).decode("utf-8")
    version = next(line.split(": ", 1)[1] for line in metadata.splitlines() if line.startswith("Version: "))
    record = {
        "tzdata_version": version,
        "wheel": wheel.name,
        "wheel_sha256": digest,
        "python_reader": sys.version.split()[0],
        "upstream_reader_sha256": source_hashes,
        "local_changes": "Python 3.7 syntax/positional parameters, strict zip replacement, truncated-footer guard, explicit TZif loading",
    }
    target.joinpath("versions.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("sha256")
    args = parser.parse_args()
    prepare(args.wheel, args.sha256)
