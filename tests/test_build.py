import ast
import gettext
import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
from string import Formatter
from zipfile import ZipFile

import polib

ROOT = Path(__file__).resolve().parents[1]


def test_turkish_catalog_covers_source_and_preserves_placeholders():
    base = ROOT / "prayerTimes"
    keys = set()
    for path in (base / "globalPlugins/prayerTimes").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
                keys.add(ast.literal_eval(node.args[0]))
    po = polib.pofile(str(base / "locale/tr/LC_MESSAGES/nvda.po"))
    with (base / "locale/tr/LC_MESSAGES/nvda.mo").open("rb") as stream:
        mo = gettext.GNUTranslations(stream)
    entries = {e.msgid: e for e in po if not e.obsolete}
    for key in keys:
        entry = entries[key]
        assert entry.msgstr and not entry.fuzzy and mo.gettext(key) == entry.msgstr

        def fields(value):
            return {field for _, field, _, _ in Formatter().parse(value) if field is not None}

        assert fields(key) == fields(entry.msgstr)


def test_reproducible_clean_addon_with_compiled_catalog_and_data(tmp_path):
    spec = importlib.util.spec_from_file_location("build_addon_test", ROOT / "tools/build_addon.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    first = builder.build(tmp_path / "first.nvda-addon")
    second = builder.build(tmp_path / "second.nvda-addon")
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    with ZipFile(first) as archive:
        names = archive.namelist()
        assert "manifest.ini" in names and "COPYING.txt" in names and "DOC/tr/readme.html" in names
        assert "globalPlugins/prayerTimes/_vendor/timezones.zip" in names
        assert not any(
            "__pycache__" in name or name.endswith((".pyc", ".pyo")) or name.startswith(("tests/", "tools/"))
            for name in names
        )
        mo = gettext.GNUTranslations(BytesIO(archive.read("locale/tr/LC_MESSAGES/nvda.mo")))
        assert mo.gettext("Sunrise") == "Güneş"
