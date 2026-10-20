import importlib
from pathlib import Path
import sys
import types

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "prayerTimes/globalPlugins/prayerTimes"
package = types.ModuleType("prayer_test")
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package
service = importlib.import_module("prayer_test.service")


@pytest.fixture
def svc():
    return service
