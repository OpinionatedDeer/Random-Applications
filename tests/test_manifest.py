"""Structural rules for the changing kind's generated manifest and resources.

aapt2 does not check that component classes exist, so a wrong name would only fail on the
device (install error or ClassNotFoundException). These tests apply Android's own name
resolution rules to the rendered manifest instead.
"""
import re
import unittest
import xml.etree.ElementTree as ET
from argparse import Namespace
from types import SimpleNamespace

from apkgen.kinds import changing

A = "{http://schemas.android.com/apk/res/android}"


def resolve_class(pkg, name):
    """Android's rule (ParsingUtils.buildClassName)."""
    if name.startswith("."):
        return pkg + name
    if "." not in name:
        return f"{pkg}.{name}"
    return name


def options(**overrides):
    args = dict(start=1, end=4, frames=4, interval=60, phase="sync", label_mode="same",
                wakeup=False, whitelist=False, install=False, launch=False)
    args.update(overrides)
    return changing.options_from_args(Namespace(**args))


def spec(i=1, **overrides):
    return changing.make_spec(i, options(**overrides), SimpleNamespace(font=None), "/x/classes.dex")


class ManifestRules(unittest.TestCase):
    def setUp(self):
        self.spec = spec(i=3, frames=4)
        self.root = ET.fromstring(self.spec.manifest)
        self.pkg = self.root.get("package")
        self.app = self.root.find("application")

    def test_no_placeholders_left(self):
        for text in [self.spec.manifest] + [v for v in self.spec.resources.values() if isinstance(v, str)]:
            self.assertNotIn("${", text)

    def test_real_components_live_in_runtime_package(self):
        for tag in ("activity", "receiver"):
            for el in self.app.findall(tag):
                name = resolve_class(self.pkg, el.get(A + "name"))
                self.assertTrue(name.startswith(changing.RUNTIME_PKG + "."), name)

    def test_aliases_target_entry_activity_declared_first(self):
        children = list(self.app)
        entry = f"{changing.RUNTIME_PKG}.EntryActivity"
        entry_pos = next(i for i, el in enumerate(children)
                         if el.tag == "activity" and resolve_class(self.pkg, el.get(A + "name")) == entry)
        aliases = [(i, el) for i, el in enumerate(children) if el.tag == "activity-alias"]
        self.assertEqual([el.get(A + "name") for _, el in aliases],
                         [".IconInit", ".Icon0", ".Icon1", ".Icon2", ".Icon3"])
        for pos, el in aliases:
            self.assertGreater(pos, entry_pos)
            self.assertEqual(resolve_class(self.pkg, el.get(A + "targetActivity")), entry)

    def test_exactly_one_alias_enabled_initially(self):
        enabled = [el.get(A + "name") for el in self.app.findall("activity-alias")
                   if el.get(A + "enabled") == "true"]
        self.assertEqual(enabled, [".IconInit"])

    def test_only_aliases_are_launcher_entries(self):
        for el in self.app.findall("activity"):
            self.assertIsNone(el.find("intent-filter"), el.get(A + "name"))

    def test_alias_resources_exist(self):
        strings = self.spec.resources["values/strings.xml"]
        names = set(re.findall(r'name="([^"]+)"', strings))
        for el in self.app.findall("activity-alias"):
            icon = el.get(A + "icon").removeprefix("@drawable/")
            label = el.get(A + "label").removeprefix("@string/")
            self.assertIn(f"drawable-xxxhdpi/{icon}.png", self.spec.resources)
            self.assertIn(label, names)

    def test_meta_data(self):
        md = {el.get(A + "name"): el.get(A + "value") for el in self.app.findall("meta-data")}
        self.assertEqual(md, {"iconswitch.app": "3", "iconswitch.frames": "4",
                              "iconswitch.interval_ms": "60000", "iconswitch.phase_ms": "0",
                              "iconswitch.wakeup": "false"})

    def test_launch_bootstraps_entry_activity(self):
        self.assertIn(f"{self.pkg}/{changing.RUNTIME_PKG}.EntryActivity", self.spec.launch)
        self.assertEqual(self.spec.dex, "/x/classes.dex")

    def test_post_install_always_restores(self):
        restore = ("am", "broadcast", "-f", "0x20", "-n", f"{self.pkg}/{changing.RUNTIME_PKG}.SwitchReceiver",
                   "-a", changing.ACTION_PREFIX + "RESTORE")
        self.assertEqual(self.spec.post_install, (restore,))

    def test_receiver_handles_boot_update_and_clock_changes(self):
        actions = {a.get(A + "name") for a in self.app.find("receiver").iter("action")}
        self.assertEqual(actions, {"android.intent.action.BOOT_COMPLETED",
                                   "android.intent.action.MY_PACKAGE_REPLACED",
                                   "android.intent.action.TIME_SET"})


class Options(unittest.TestCase):
    def test_stagger_phase_depends_only_on_app_number(self):
        def phase(i, **kw):
            root = ET.fromstring(changing.make_spec(i, options(phase="stagger", **kw),
                                                    SimpleNamespace(font=None), "d").manifest)
            md = {el.get(A + "name"): el.get(A + "value") for el in root.find("application").findall("meta-data")}
            return int(md["iconswitch.phase_ms"])
        phases = [phase(i, start=10, end=29) for i in range(10, 30)]
        self.assertTrue(all(0 <= p < 60000 for p in phases))
        self.assertEqual(len(set(phases)), len(phases))
        # roughly even: every quarter of the interval gets some apps
        self.assertEqual({p * 4 // 60000 for p in phases}, {0, 1, 2, 3})
        self.assertEqual(phase(17, start=10, end=29), phase(17, start=1, end=500))

    def test_label_mode_frame(self):
        strings = spec(i=5, label_mode="frame", frames=2).resources["values/strings.xml"]
        self.assertIn('<string name="label_1">S5 f1</string>', strings)
        self.assertIn('<string name="label_init">S5 init</string>', strings)

    def test_whitelist_adds_post_install_and_requires_install(self):
        commands = spec(i=2, whitelist=True, install=True).post_install
        self.assertEqual(commands[0], ("cmd", "deviceidle", "whitelist", "+com.test.iconswitch.app2"))
        self.assertEqual(commands[1][-1], changing.ACTION_PREFIX + "RESTORE")
        with self.assertRaises(ValueError):
            options(whitelist=True)

    def test_validation(self):
        for bad in (dict(frames=1), dict(frames=37), dict(interval=9)):
            with self.subTest(**bad), self.assertRaises(ValueError):
                options(**bad)


class Runtime(unittest.TestCase):
    def java(self, name):
        return changing.runtime_sources()[changing.RUNTIME_PKG.replace(".", "/") + f"/{name}.java"]

    def test_meta_data_keys_match_java(self):
        keys = set(re.findall(r'(?:number|bool)\(md, "([^"]+)"\)', self.java("Config")))
        root = ET.fromstring(spec().manifest)
        self.assertEqual(keys, {el.get(A + "name") for el in root.find("application").findall("meta-data")})

    def test_alias_names_match_java(self):
        java = self.java("IconSwitcher")
        self.assertIn('return "IconInit";', java)
        self.assertIn('return "Icon" + frame;', java)

    def test_restore_action_exists(self):
        self.assertIn('ACTION_RESTORE = ACTION_PREFIX + "RESTORE"', self.java("Config"))
        self.assertIn("case Config.ACTION_RESTORE:", self.java("SwitchReceiver"))

    def test_action_prefix_matches_java(self):
        config_java = changing.runtime_sources()[changing.RUNTIME_PKG.replace(".", "/") + "/Config.java"]
        self.assertIn(f'ACTION_PREFIX = "{changing.ACTION_PREFIX}"', config_java)
        for action in changing.SIGNAL_ACTIONS:
            self.assertIn(f'ACTION_{action.upper()} = ACTION_PREFIX + "{action.upper()}"', config_java)

    def test_runtime_package_matches_sources(self):
        sources = changing.runtime_sources()
        self.assertEqual(len(sources), 5)
        for rel, text in sources.items():
            self.assertTrue(rel.startswith(changing.RUNTIME_PKG.replace(".", "/") + "/"), rel)
            self.assertIn(f"package {changing.RUNTIME_PKG};", text)
            self.assertIsNone(re.search(r"\bR\.", text), f"{rel} must not reference R (shared dex)")


if __name__ == "__main__":
    unittest.main()
