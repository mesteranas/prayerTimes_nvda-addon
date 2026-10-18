"""Import the real plugin with controlled NVDA/wx boundaries; no screen-reader claims."""

import ast
import gettext
import importlib.util
import inspect
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plugin(monkeypatch):
    def load(existing=True, legacy=False):
        original_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.name == "_installation.json":
                return '{"preserve_legacy_method": true}' if legacy else '{"preserve_legacy_method": false}'
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_text)
        name = "plugin_under_test"
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                monkeypatch.delitem(sys.modules, key)
        with (ROOT / "prayerTimes/locale/tr/LC_MESSAGES/nvda.mo").open("rb") as stream:
            tr = gettext.GNUTranslations(stream)

        def init_translation():
            inspect.currentframe().f_back.f_globals["_"] = tr.gettext

        monkeypatch.setitem(
            sys.modules, "addonHandler", types.SimpleNamespace(initTranslation=init_translation)
        )

        class Section(dict):
            def __init__(self, values, spec):
                super().__init__(values)
                self.spec = spec

            def __missing__(self, key):
                rule = self.spec[key]
                call = ast.parse(rule, mode="eval").body
                default = next(kw.value for kw in call.keywords if kw.arg == "default")
                if isinstance(default, ast.Name):
                    value = {"true": True, "false": False}[default.id]
                else:
                    value = ast.literal_eval(default)
                value = str(value) if call.func.id == "string" else value
                self[key] = value
                return value

        class Config:
            """Model NVDA's cached section/spec binding, including membership reads."""

            def __init__(self, values):
                self.spec = {}
                self.profiles = [values]
                self.cache = {}

            def __contains__(self, key):
                try:
                    self[key]
                except KeyError:
                    return False
                return True

            def __getitem__(self, key):
                if key in self.cache:
                    value = self.cache[key]
                    if value is KeyError:
                        raise KeyError(key)
                    return value
                if key not in self.spec and key not in self.profiles[0]:
                    self.cache[key] = KeyError
                    raise KeyError(key)
                # NVDA creates an empty spec for an existing unregistered section.
                # Replacing the parent spec later leaves this object bound to it.
                spec = self.spec.setdefault(key, {})
                value = Section(self.profiles[0].get(key, {}), spec)
                self.cache[key] = value
                return value

        conf = Config(
            {"prayerTimes": {"auto_detect": False, "lat": "41.0", "lon": "29.0"}} if existing else {}
        )
        monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(conf=conf))
        messages, queue, workers, errors = [], [], [], []

        class BasePlugin:
            def terminate(self):
                self.base_terminated = True

        monkeypatch.setitem(
            sys.modules, "globalPluginHandler", types.SimpleNamespace(GlobalPlugin=BasePlugin)
        )
        gui = types.ModuleType("gui")
        gui.guiHelper = types.SimpleNamespace()
        gui.messageBox = lambda *args, **kwargs: errors.append(args)
        settings = types.SimpleNamespace(
            SettingsPanel=type("SettingsPanel", (), {}),
            NVDASettingsDialog=types.SimpleNamespace(categoryClasses=[]),
        )
        monkeypatch.setitem(sys.modules, "gui", gui)
        monkeypatch.setitem(sys.modules, "gui.settingsDialogs", settings)
        wx = types.SimpleNamespace(
            Dialog=type("Dialog", (), {}),
            CallAfter=lambda func, *args: queue.append((func, args)),
            OK=1,
            ICON_ERROR=2,
            WXK_ESCAPE=27,
        )
        monkeypatch.setitem(sys.modules, "wx", wx)
        monkeypatch.setitem(sys.modules, "ui", types.SimpleNamespace(message=messages.append))
        monkeypatch.setitem(
            sys.modules,
            "logHandler",
            types.SimpleNamespace(
                log=types.SimpleNamespace(warning=lambda *args: None, exception=lambda *args: None)
            ),
        )
        monkeypatch.setitem(
            sys.modules, "scriptHandler", types.SimpleNamespace(script=lambda **kwargs: lambda fn: fn)
        )
        spec = importlib.util.spec_from_file_location(
            name,
            ROOT / "prayerTimes/globalPlugins/prayerTimes/__init__.py",
            submodule_search_locations=[str(ROOT / "prayerTimes/globalPlugins/prayerTimes")],
        )
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)

        class Worker:
            def __init__(self, target, args, **kwargs):
                assert kwargs["daemon"] is True
                self.target, self.args = target, args

            def start(self):
                workers.append(self)

            def run(self):
                self.target(*self.args)

        monkeypatch.setattr(module, "threading", types.SimpleNamespace(Thread=Worker))
        return types.SimpleNamespace(
            module=module, conf=conf, messages=messages, queue=queue, workers=workers, errors=errors
        )

    return load


def finish(env):
    function, args = env.queue.pop(0)
    function(*args)


def test_existing_and_new_method_defaults(plugin):
    assert plugin(existing=True).module.read_options().method == 5
    assert plugin(existing=False).module.read_options().method == -1


def test_v20_upgrade_without_saved_settings_preserves_method(plugin):
    assert plugin(existing=False, legacy=True).module.read_options().method == 5


@pytest.mark.parametrize("existing", [True, False])
def test_partial_or_new_config_resolves_defaults_after_schema_registration(plugin, existing):
    env = plugin(existing=existing)
    values = env.conf["prayerTimes"]
    assert values["auto_detect"] is (not existing)
    assert values["school"] == 0
    assert values["latitude_adjustment"] == 3
    assert values["use_24h"] is True
    # The section must hold the registered schema, not a stale empty mapping.
    assert values.spec is env.conf.spec["prayerTimes"]
    obj = env.module.GlobalPlugin()
    obj._request("next")
    assert len(env.workers) == 1


def test_installation_records_old_version_without_touching_config(plugin, tmp_path):
    plugin()
    import json

    spec = importlib.util.spec_from_file_location("install_test", ROOT / "prayerTimes/installTasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = types.SimpleNamespace(manifest={"name": "prayerTimes", "version": "2.0"})
    new = types.SimpleNamespace(manifest={"name": "prayerTimes", "version": "2.1.0-dev"})
    module.record_installation(tmp_path, [old, new])
    # Use read_bytes to bypass the controlled plugin marker reader above.
    assert json.loads((tmp_path / "_installation.json").read_bytes())["preserve_legacy_method"] is True
    module.record_installation(tmp_path, [new])
    assert json.loads((tmp_path / "_installation.json").read_bytes())["preserve_legacy_method"] is False


def test_translations_and_all_method_ids(plugin):
    mod = plugin().module
    assert mod.handler.prayer_name("Fajr") == "İmsak (Sabah)"
    assert mod.handler.prayer_name("Sunrise") == "Güneş"
    assert set(key for key, _ in mod.handler.methods()) == set(
        mod.Options.__post_init__.__globals__["METHOD_IDS"]
    )


def test_repeated_commands_share_one_worker(plugin, monkeypatch):
    env = plugin()
    obj = env.module.GlobalPlugin()
    obj._request("next")
    obj._request("next")
    assert len(env.workers) == 1
    calls = []
    monkeypatch.setattr(obj._service, "get_data", lambda *args, **kwargs: calls.append(True))
    env.workers.pop().run()
    finish(env)
    assert len(calls) == 1 and not obj._busy


def test_network_failure_is_announced_without_parsing(plugin, monkeypatch):
    env = plugin()
    obj = env.module.GlobalPlugin()

    def fail(*args, **kwargs):
        raise env.module.PrayerError("timeout")

    monkeypatch.setattr(obj._service, "get_data", fail)
    obj._request("next")
    env.workers.pop().run()
    finish(env)
    assert "zaman aşımına" in env.messages[-1]
    assert not obj._busy


def test_save_invalidates_queued_result_and_new_request_waits(plugin, monkeypatch):
    env = plugin()
    obj = env.module.GlobalPlugin()
    monkeypatch.setattr(obj._service, "get_data", lambda *args, **kwargs: "old data")
    obj._request("current")
    worker = env.workers.pop()
    worker.run()
    obj.invalidate()
    obj._request("next")
    assert not env.workers  # old callback still owns the worker slot
    finish(env)  # Must not try to format the old string as structured data.
    assert len(env.workers) == 1 and env.workers[0].args[0] == env.module.read_options()


def test_profile_switch_restarts_without_announcing_old_result(plugin, monkeypatch):
    env = plugin()
    obj = env.module.GlobalPlugin()
    monkeypatch.setattr(obj._service, "get_data", lambda *args, **kwargs: "old data")
    obj._request("next")
    env.workers.pop().run()
    env.conf["prayerTimes"]["method"] = 13
    finish(env)
    assert len(env.workers) == 1 and env.workers[0].args[0].method == 13


def test_terminate_blocks_queued_gui_work(plugin, monkeypatch):
    env = plugin()
    obj = env.module.GlobalPlugin()
    monkeypatch.setattr(obj._service, "get_data", lambda *args, **kwargs: "old data")
    obj._request("current")
    env.workers.pop().run()
    obj.terminate()
    finish(env)
    assert not env.workers and obj.base_terminated
    assert not env.module.NVDASettingsDialog.categoryClasses


class Control:
    def __init__(self, value):
        self.value, self.focused, self.enabled = value, False, True

    def GetValue(self):
        return self.value

    def GetSelection(self):
        return self.value

    def SetFocus(self):
        self.focused = True

    def Enable(self, enabled):
        self.enabled = enabled


def make_panel(mod, lat, lon, auto=False):
    panel = mod.PrayerSettingsPanel()
    panel.auto_detect, panel.lat_ctrl, panel.lon_ctrl = Control(auto), Control(lat), Control(lon)
    panel._methods = mod.handler.methods()
    panel.method = Control(next(i for i, (key, _) in enumerate(panel._methods) if key == 13))
    panel.school, panel.latitude_adjustment, panel.use_24h = Control(1), Control(2), Control(True)
    return panel


def test_manual_validation_and_normalized_save(plugin):
    env = plugin()
    panel = make_panel(env.module, "nan", "29")
    assert panel.isValid() is False and panel.lat_ctrl.focused and env.errors
    panel.lat_ctrl.value = "41,0082"
    panel.lon_ctrl.value = "28,9784"
    assert panel.isValid() is True
    obj = env.module.GlobalPlugin()
    panel.onSave()
    assert env.conf["prayerTimes"]["lat"] == "41.0082"
    assert env.conf["prayerTimes"]["method"] == 13
    assert env.conf["prayerTimes"]["school"] == 1 and obj._generation == 1


def test_auto_location_disables_coordinates_and_ignores_unused_invalid_input(plugin):
    env = plugin()
    panel = make_panel(env.module, "bad", "bad", auto=True)
    panel.on_toggle_auto(None)
    assert not panel.lat_ctrl.enabled and not panel.lon_ctrl.enabled and panel.isValid()


def test_escape_close_and_other_keys_propagate(plugin):
    mod = plugin().module
    closed, skipped = [], []
    event = types.SimpleNamespace(GetKeyCode=lambda: 27, Skip=lambda: skipped.append(True))
    receiver = types.SimpleNamespace(Close=lambda: closed.append(True))
    mod.ResultDialog._on_key(receiver, event)
    assert closed and not skipped
    event.GetKeyCode = lambda: 40
    mod.ResultDialog._on_key(receiver, event)
    assert skipped
