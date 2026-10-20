"""Preserve V2.0 defaults even when no add-on settings section was saved."""

import json
from pathlib import Path

import addonHandler


def record_installation(root, addons):
    legacy = any(
        addon.manifest["name"] == "prayerTimes" and addon.manifest["version"] == "2.0" for addon in addons
    )
    (root / "_installation.json").write_text(
        json.dumps({"preserve_legacy_method": legacy}) + "\n", encoding="utf-8"
    )


def onInstall():
    record_installation(Path(__file__).parent, addonHandler.getAvailableAddons())
