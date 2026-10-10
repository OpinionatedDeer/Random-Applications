"""Pure helpers of the build pipeline (no SDK needed)."""
import unittest

from apkgen import apk
from apkgen.apk import BuildError


class Helpers(unittest.TestCase):
    def test_redact_keystore_password(self):
        cmd = ["apksigner", "sign", "--ks", "k", "--ks-pass", "pass:hunter2", "--out", "o", "i"]
        self.assertNotIn("hunter2", apk._redact(cmd))
        self.assertIn("--ks-pass pass:***", apk._redact(cmd))
        self.assertIn("env:PW", apk._redact(["apksigner", "--ks-pass", "env:PW"]))

    def test_build_error_pickles(self):
        import pickle
        e = pickle.loads(pickle.dumps(BuildError("d8", "boom")))
        self.assertEqual((e.step, e.message, str(e)), ("d8", "boom", "d8: boom"))

    def test_failed_command_raises_build_error_with_output(self):
        with self.assertRaises(BuildError) as ctx:
            apk.run("sh", ["sh", "-c", "echo bad >&2; exit 3"])
        self.assertIn("exit 3", str(ctx.exception))
        self.assertIn("bad", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
