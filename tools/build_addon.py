"""Build a reproducible local NVDA add-on with verified translation catalogs."""

import ast
import gettext
import hashlib
import json
from pathlib import Path
import re
from string import Formatter
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import polib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prayerTimes"


def fields(value):
    return {name for _text, name, _spec, _conversion in Formatter().parse(value) if name is not None}


def build(destination=None):
    manifest = (SOURCE / "manifest.ini").read_text(encoding="utf-8")
    version = re.search(r"^version\s*=\s*(\S+)", manifest, re.M).group(1)
    keys = set()
    for source in (SOURCE / "globalPlugins/prayerTimes").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
                keys.add(ast.literal_eval(node.args[0]))
    catalogs = {}
    for source in sorted((SOURCE / "locale").glob("*/LC_MESSAGES/nvda.po")):
        catalog = polib.pofile(str(source))
        language = source.parents[1].name
        entries = {e.msgid: e for e in catalog if not e.obsolete}
        if not keys <= entries.keys():
            raise ValueError(f"{language}: stale PO template")
        for entry in entries.values():
            if entry.msgstr and fields(entry.msgid) != fields(entry.msgstr):
                raise ValueError(f"{language}: invalid format placeholders: {entry.msgid}")
        if language == "tr" and any(not entries[key].msgstr or entries[key].fuzzy for key in keys):
            raise ValueError("Incomplete Turkish translations")
        data = catalog.to_binary()
        catalogs[source.with_suffix(".mo").relative_to(SOURCE).as_posix()] = data
        from io import BytesIO

        loaded = gettext.GNUTranslations(BytesIO(data))
        for entry in entries.values():
            if entry.msgstr and not entry.fuzzy:
                assert loaded.gettext(entry.msgid) == entry.msgstr
    destination = destination or ROOT / "dist" / f"prayerTimes-{version}.nvda-addon"
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = {}
    for source in sorted(SOURCE.rglob("*")):
        if (
            not source.is_file()
            or "__pycache__" in source.parts
            or source.name == "_installation.json"
            or source.suffix in (".pyc", ".pyo")
        ):
            continue
        name = source.relative_to(SOURCE).as_posix()
        content[name] = catalogs.get(name, source.read_bytes())
    content.update(catalogs)
    content["COPYING.txt"] = (ROOT / "LICENSE").read_bytes()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    record = {
        "file": destination.name,
        "version": version,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "entries": len(content),
    }
    destination.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))
    return destination


if __name__ == "__main__":
    build()
