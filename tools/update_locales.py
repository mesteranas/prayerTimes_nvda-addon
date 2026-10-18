"""Extract literal gettext keys, merge catalogs and compile MO files."""

import ast
from datetime import datetime, timezone
from pathlib import Path
import re
import polib

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "prayerTimes"


def update():
    occurrences = {}
    for source in sorted((BASE / "globalPlugins/prayerTimes").glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
                key = ast.literal_eval(node.args[0])
                occurrences.setdefault(key, []).append(
                    (source.relative_to(BASE).as_posix(), str(node.lineno))
                )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M+0000")
    version = re.search(
        r"^version\s*=\s*(\S+)", (BASE / "manifest.ini").read_text(encoding="utf-8"), re.M
    ).group(1)
    pot = polib.POFile()
    pot.metadata = {
        "Project-Id-Version": f"prayerTimes {version}",
        "POT-Creation-Date": stamp,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }
    for key, locations in sorted(occurrences.items()):
        pot.append(polib.POEntry(msgid=key, occurrences=locations))
    pot.save(str(BASE / "locale/messages.pot"))
    for source in sorted((BASE / "locale").glob("*/LC_MESSAGES/nvda.po")):
        catalog = polib.pofile(str(source))
        catalog.merge(pot)
        catalog.metadata["Project-Id-Version"] = f"prayerTimes {version}"
        catalog.save(str(source))
        catalog.save_as_mofile(str(source.with_suffix(".mo")))
    print(f"Updated {len(occurrences)} translation keys")


if __name__ == "__main__":
    update()
