"""Config lookup and precedence rules, using a fake SDK so no real toolchain is needed."""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from apkgen import config
from apkgen.config import ConfigError


def make_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def make_sdk(root, versions=("34.0.0",), complete=True):
    for v in versions:
        for tool in config.BUILD_TOOLS if complete else ("aapt2",):
            make_exe(root / "build-tools" / v / tool)
    jar = root / "platforms" / "android-30" / "android.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_bytes(b"")
    return root


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.env = {"HOME": str(self.tmp)}

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, text, name="cfg.toml"):
        path = self.tmp / name
        path.write_text(text)
        return str(path)

    def rows(self, cfg, env=None):
        _tc, rows, problems = config._resolve(cfg, self.env if env is None else env, need_adb=False)
        return {k: (v, origin) for k, v, origin in rows}, problems

    def test_file_beats_env(self):
        a, b = make_sdk(self.tmp / "sdkA"), make_sdk(self.tmp / "sdkB")
        cfg = self.write_config(f'[toolchain]\nsdk_dir = "{a}"\n')
        rows, _ = self.rows(cfg, {**self.env, "ANDROID_HOME": str(b)})
        self.assertEqual(rows["sdk_dir"], (str(a), "config"))

    def test_env_beats_auto(self):
        b = make_sdk(self.tmp / "sdkB")
        cfg = self.write_config("[toolchain]\n")
        rows, _ = self.rows(cfg, {**self.env, "ANDROID_HOME": str(b)})
        self.assertEqual(rows["sdk_dir"], (str(b), "env ANDROID_HOME"))

    def test_newest_complete_build_tools(self):
        sdk = make_sdk(self.tmp / "sdk", versions=("9.0.0", "30.0.3", "36.0.0-rc1", "35.0.0"))
        make_sdk(sdk, versions=("37.0.0",), complete=False)  # newest but missing d8 etc.
        self.assertEqual(config._newest_build_tools(str(sdk)), "36.0.0-rc1")  # numeric, not lexical
        make_sdk(sdk, versions=("36.0.0",))
        self.assertEqual(config._newest_build_tools(str(sdk)), "36.0.0")  # release beats its rc

    def test_relative_paths_resolve_against_config_dir(self):
        (self.tmp / "sub").mkdir()
        cfg = self.write_config('[toolchain]\nsdk_dir = "sdk"\nkeystore = "keys/debug.keystore"\n',
                                name="sub/cfg.toml")
        rows, _ = self.rows(cfg)
        self.assertEqual(rows["sdk_dir"][0], str(self.tmp / "sub" / "sdk"))
        self.assertEqual(rows["keystore"][0], str(self.tmp / "sub" / "keys" / "debug.keystore"))

    def test_unknown_key_and_table_reported(self):
        cfg = self.write_config('[toolchain]\nsdk_dirr = "x"\n[other]\na = 1\n')
        _, problems = self.rows(cfg)
        self.assertTrue(any("sdk_dirr" in p for p in problems))
        self.assertTrue(any("'other'" in p for p in problems))

    def test_invalid_toml_reports_location(self):
        cfg = self.write_config("[toolchain\n")
        _, problems = self.rows(cfg)
        self.assertTrue(any("line 1" in p for p in problems), problems)

    def test_explicit_missing_config_is_error(self):
        with self.assertRaises(ConfigError):
            config.find_config(str(self.tmp / "nope.toml"), self.env)
        with self.assertRaises(ConfigError):
            config.find_config(None, {**self.env, "APKGEN_CONFIG": str(self.tmp / "nope.toml")})

    def test_resolve_reports_all_problems(self):
        cfg = self.write_config(f'[toolchain]\nsdk_dir = "{self.tmp / "missing"}"\n'
                                f'keystore = "{self.tmp / "no.keystore"}"\n')
        with self.assertRaises(ConfigError) as ctx:
            config.resolve(cfg, env=self.env)
        text = str(ctx.exception)
        self.assertIn("sdk_dir is not a directory", text)
        self.assertIn("keystore not found", text)
        self.assertIn("android.jar not found", text)

    def test_non_utf8_config_reported(self):
        path = self.tmp / "latin1.toml"
        path.write_bytes(b'[toolchain]\nfont = "caf\xe9.ttf"\n')
        _, problems = self.rows(str(path))
        self.assertTrue(any("not valid UTF-8" in p for p in problems), problems)

    def test_empty_value_reported(self):
        _, problems = self.rows(self.write_config('[toolchain]\njavac = ""\n'))
        self.assertTrue(any("toolchain.javac is empty" in p for p in problems), problems)

    def test_keystore_pass_checks(self):
        (self.tmp / "sub").mkdir()
        cfg = self.write_config('[toolchain]\nkeystore_pass = "file:pw.txt"\n', name="sub/cfg.toml")
        rows, problems = self.rows(cfg)
        self.assertEqual(rows["keystore_pass"][0], "file:" + str(self.tmp / "sub" / "pw.txt"))
        self.assertTrue(any("password file not found" in p for p in problems), problems)
        _, problems = self.rows(self.write_config('[toolchain]\nkeystore_pass = "env:NO_SUCH_VAR"\n'))
        self.assertTrue(any("NO_SUCH_VAR is not set" in p for p in problems), problems)
        _, problems = self.rows(self.write_config('[toolchain]\nkeystore_pass = "android"\n'))
        self.assertTrue(any("apksigner syntax" in p for p in problems), problems)

    def test_doctor_masks_password(self):
        lines, _ok, _tc = config.doctor_report(self.write_config('[toolchain]\nkeystore_pass = "pass:secret"\n'),
                                               self.env)
        text = "\n".join(lines)
        self.assertNotIn("secret", text)
        self.assertIn("pass:***", text)

    def test_adb_only_resolve_ignores_build_problems(self):
        adb = self.tmp / "bin" / "adb"
        make_exe(adb)
        cfg = self.write_config(f'[toolchain]\nsdk_dir = "{self.tmp / "missing"}"\nadb = "{adb}"\n')
        with self.assertRaises(ConfigError):
            config.resolve(cfg, env=self.env)
        self.assertEqual(config.resolve_adb(cfg, env=self.env).adb, str(adb))
        bad = self.write_config(f'[toolchain]\nadb = "{self.tmp / "nope"}"\n', name="bad.toml")
        with self.assertRaises(ConfigError):
            config.resolve_adb(bad, env=self.env)

    def test_lookup_order(self):
        cwd = self.tmp / "work"
        cwd.mkdir()
        (cwd / config.LOCAL_CONFIG_NAME).write_text("[toolchain]\n")
        explicit = self.write_config("[toolchain]\n", name="explicit.toml")
        old = os.getcwd()
        os.chdir(cwd)
        try:
            self.assertEqual(config.find_config(None, self.env), str(cwd / config.LOCAL_CONFIG_NAME))
            self.assertEqual(config.find_config(None, {**self.env, "APKGEN_CONFIG": explicit}), explicit)
            self.assertEqual(config.find_config(explicit, {**self.env, "APKGEN_CONFIG": "/nope"}), explicit)
        finally:
            os.chdir(old)

    def test_tool_env_puts_java_first_on_path(self):
        sdk = make_sdk(self.tmp / "sdk")
        tc, _, _ = config._resolve(self.write_config(f'[toolchain]\nsdk_dir = "{sdk}"\njava = "/opt/jdk/bin/java"\n'),
                                   self.env, need_adb=False)
        self.assertTrue(tc.tool_env()["PATH"].startswith("/opt/jdk/bin" + os.pathsep))


if __name__ == "__main__":
    unittest.main()
