import os
import shutil
import subprocess
import sys
import argparse
import multiprocessing
from PIL import Image, ImageDraw, ImageFont

from config import ConfigError, resolve

def run(cmd, cwd=None, env=None):
    # We don't print every command in parallel mode to avoid messy output
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Command failed: {' '.join(cmd)}\nError: {result.stderr}")
    return result.stdout

def build_app(app_id, app_name, icon_num, output_dir, install, tc):
    try:
        work_dir = os.path.join(output_dir, f"tmp_{app_id}")
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        os.makedirs(work_dir)

        # 1. Create Folder Structure
        package_path = app_id.replace('.', '/')
        src_dir = os.path.join(work_dir, "src", package_path)
        res_dir = os.path.join(work_dir, "res")
        os.makedirs(src_dir)
        os.makedirs(os.path.join(res_dir, "drawable"))
        os.makedirs(os.path.join(res_dir, "values"))

        # 2. Create MainActivity.java
        with open(os.path.join(src_dir, "MainActivity.java"), "w") as f:
            f.write(f"""package {app_id};

import android.app.Activity;
import android.os.Bundle;

public class MainActivity extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
    }}
}}
""")

        # 3. Create AndroidManifest.xml
        with open(os.path.join(work_dir, "AndroidManifest.xml"), "w") as f:
            f.write(f"""<?xml version="1.0" encoding="utf-8"?>
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
""")

        # 4. Create strings.xml
        with open(os.path.join(res_dir, "values", "strings.xml"), "w") as f:
            f.write(f'<resources><string name="app_name">{app_name}</string></resources>')

        # 5. Generate Icon
        icon_path = os.path.join(res_dir, "drawable", "ic_launcher.png")
        img = Image.new('RGB', (512, 512), color=(icon_num % 255, (icon_num * 7) % 255, (icon_num * 13) % 255))
        
        try:
            draw = ImageDraw.Draw(img)
            if tc.font:
                font = ImageFont.truetype(tc.font, 256)
            else:
                font = ImageFont.load_default()
            
            text = str(icon_num)
            if hasattr(draw, 'textbbox'):
                bbox = draw.textbbox((0, 0), text, font=font)
                x = (512 - bbox[0] - bbox[2]) / 2
                y = (512 - bbox[1] - bbox[3]) / 2
            else:
                text_width, text_height = draw.textsize(text, font=font)
                x = (512 - text_width) / 2
                y = (512 - text_height) / 2
            
            draw.text((x, y), text, fill=(255, 255, 255), font=font)
        except Exception as e:
            print(f"Warning: Failed to draw text on icon: {e}")

        img.save(icon_path)

        # 6. Compile Java
        run([tc.javac, "-source", "8", "-target", "8", "-cp", tc.android_jar, "-d", os.path.join(work_dir, "classes"), os.path.join(src_dir, "MainActivity.java")])

        # 7. Compile Resources
        run([tc.aapt2, "compile", "--dir", res_dir, "-o", os.path.join(work_dir, "res.flata")])

        # 8. Link Resources
        base_apk = os.path.join(work_dir, "base.apk")
        run([tc.aapt2, "link", "--manifest", os.path.join(work_dir, "AndroidManifest.xml"), 
             "-o", base_apk, "-I", tc.android_jar, os.path.join(work_dir, "res.flata")])

        # 9. Convert Classes to Dex
        dex_dir = os.path.join(work_dir, "dex")
        os.makedirs(dex_dir)
        
        class_files = []
        for root, dirs, files in os.walk(os.path.join(work_dir, "classes")):
            for file in files:
                if file.endswith(".class"):
                    class_files.append(os.path.join(root, file))
        
        if not class_files:
            raise Exception("No class files found")
            
        run([tc.d8, "--lib", tc.android_jar, "--output", dex_dir] + class_files, env=tc.tool_env())

        # 10. Add Dex to APK
        found_dex = False
        for root, dirs, files in os.walk(dex_dir):
            if "classes.dex" in files:
                dex_file = os.path.join(root, "classes.dex")
                found_dex = True
                break
        if not found_dex:
            raise Exception("classes.dex not found")

        run([tc.zip, "-uj", base_apk, dex_file])

        # 11. Align APK
        aligned_apk = os.path.join(work_dir, "aligned.apk")
        run([tc.zipalign, "-p", "4", base_apk, aligned_apk])

        # 12. Sign APK
        final_apk = os.path.join(output_dir, f"{app_id}.apk")
        run([tc.apksigner, "sign", "--ks", tc.keystore, "--ks-pass", tc.keystore_pass, "--out", final_apk, aligned_apk],
            env=tc.tool_env())

        # 13. Install if requested
        if install:
            # We use a separate subprocess for adb so it doesn't block the pool as much if it hangs, 
            # but for simplicity here we just run it.
            subprocess.run([tc.adb, "install", "-r", final_apk], capture_output=True)

        # Cleanup
        shutil.rmtree(work_dir)
        return f"Successfully built {app_id}"
    except Exception as e:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        return f"Failed to build {app_id}: {e}"

def worker_wrapper(args):
    return build_app(*args)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and optionally install Android apps.")
    parser.add_argument("output_dir", help="Directory to save the APKs")
    parser.add_argument("--start", type=int, default=1, help="Starting app number")
    parser.add_argument("--end", type=int, required=True, help="Ending app number")
    parser.add_argument("--install", action="store_true", help="Install APKs via adb after building")
    parser.add_argument("--workers", type=int, default=multiprocessing.cpu_count(), help="Number of parallel workers")
    parser.add_argument("--config", help="Toolchain config file (default: config.local.toml, see config.example.toml)")

    args = parser.parse_args()

    # Resolve machine-specific paths before creating anything, and report every problem at once.
    try:
        tc = resolve(args.config, need_adb=args.install)
    except ConfigError as e:
        print(f"build_app: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"config: {tc.config_path or 'none (auto-detect)'}", file=sys.stderr)
    for warning in tc.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        
    tasks = []
    for i in range(args.start, args.end + 1):
        app_id = f"com.test.app.app{i}"
        app_name = f"Test App {i}"
        tasks.append((app_id, app_name, i, args.output_dir, args.install, tc))
    
    print(f"Starting build of {len(tasks)} apps (from {args.start} to {args.end}) with {args.workers} workers...")
    
    with multiprocessing.Pool(processes=args.workers) as pool:
        results = pool.map(worker_wrapper, tasks)
        
    for res in results:
        print(res)
