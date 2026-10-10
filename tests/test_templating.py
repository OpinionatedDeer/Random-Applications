"""The normal kind must reproduce the original generator's text exactly: line positions are
compiled into the APK (binary manifest and dex line tables), so any drift changes the output."""
import io
import os
import unittest
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from apkgen import config, icons, templating
from apkgen.kinds import normal

FONT = next((f for f in config.FONT_CANDIDATES if os.path.isfile(f)), None)


def legacy_texts(app_id, app_name):
    """Verbatim copies of the f-strings in the original app_generator/build_app.py."""
    java = f"""package {app_id};

import android.app.Activity;
import android.os.Bundle;

public class MainActivity extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
    }}
}}
"""
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{app_id}">
    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="30" />
    <application
        android:allowBackup="true"
        android:icon="@drawable/ic_launcher"
        android:label="{app_name}"
        android:theme="@android:style/Theme.NoTitleBar">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
    strings = f'<resources><string name="app_name">{app_name}</string></resources>'
    return java, manifest, strings


class NormalKindTemplates(unittest.TestCase):
    def test_matches_legacy_output(self):
        tc = SimpleNamespace(font=None)
        for i in (1, 255, 1000):
            with self.subTest(app=i):
                spec = normal.make_spec(i, normal.Options(), tc)
                java, manifest, strings = legacy_texts(f"com.test.app.app{i}", f"Test App {i}")
                self.assertEqual(spec.package, f"com.test.app.app{i}")
                self.assertEqual(spec.manifest, manifest)
                self.assertEqual(spec.resources["values/strings.xml"], strings)
                self.assertEqual(spec.java_sources[f"com/test/app/app{i}/MainActivity.java"], java)
                self.assertEqual(set(spec.resources), {"values/strings.xml", "drawable/ic_launcher.png"})
                self.assertTrue(spec.resources["drawable/ic_launcher.png"].startswith(b"\x89PNG"))


def legacy_icon(n, font_path):
    """Verbatim copy of the icon code in the original build_app.py (TrueType branch)."""
    img = Image.new('RGB', (512, 512), color=(n % 255, (n * 7) % 255, (n * 13) % 255))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 256)
    text = str(n)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (512 - bbox[0] - bbox[2]) / 2
    y = (512 - bbox[1] - bbox[3]) / 2
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class NormalIcon(unittest.TestCase):
    @unittest.skipUnless(FONT, "no TrueType font installed")
    def test_matches_legacy_icon(self):
        for n in (1, 254, 255, 256, 1000):
            with self.subTest(app=n):
                self.assertEqual(icons.render_number_icon(n, FONT), legacy_icon(n, FONT))

    def test_size_and_colour(self):
        img = Image.open(io.BytesIO(icons.render_number_icon(300, None)))
        self.assertEqual(img.size, (512, 512))
        self.assertEqual(img.getpixel((2, 2)), (300 % 255, 300 * 7 % 255, 300 * 13 % 255))


class Substitution(unittest.TestCase):
    def test_missing_placeholder_raises(self):
        with self.assertRaises(KeyError):
            templating.render("apkgen.kinds.normal", "AndroidManifest.xml.tmpl", package="x")

    def test_xml_escape(self):
        self.assertEqual(templating.xml_escape("Test App 1"), "Test App 1")
        self.assertEqual(templating.xml_escape('A&B <"x">'), "A&amp;B &lt;&quot;x&quot;&gt;")
        self.assertEqual(templating.xml_escape("@home"), "\\@home")

    def test_aapt_string(self):
        self.assertEqual(templating.aapt_string("Test App 1"), "Test App 1")
        self.assertEqual(templating.aapt_string("it's \"q\" & <b>"), "it\\'s \\\"q\\\" &amp; &lt;b&gt;")
        self.assertEqual(templating.aapt_string("?x"), "\\?x")


if __name__ == "__main__":
    unittest.main()
