# Android App Generator

A lightweight tool to generate and install a large number of unique Android applications for performance testing (e.g., testing an Android launcher). It bypasses the heavy Gradle build system by using a custom Python-based toolchain.

## Features

- **Mass Generation**: Quickly generate hundreds of unique APKs.
- **Unique Package Names**: Each app has a distinct package name (e.g., `com.test.app.app1`).
- **Numbered Icons**: Each app icon features its respective application number for easy visual identification.
- **Parallel Building**: Uses `multiprocessing` to speed up the generation process.
- **Direct Installation**: Optionally installs each APK via `adb` immediately after a successful build.

## Prerequisites

- **Python 3.11+** with `Pillow` installed (`pip install Pillow`).
- **Java Development Kit (JDK)**: `javac` and `java` (found via config, `JAVA_HOME`, or `PATH`).
- **Android SDK** with:
  - Build Tools (e.g. `36.0.0`) providing `aapt2`, `d8`, `zipalign`, `apksigner`. They do *not* need to be on `PATH`; they are located inside the SDK.
  - An Android platform (default `android-30`).
- **zip** on `PATH`.
- **ADB** (only for `--install`): on `PATH` or in the SDK's `platform-tools`, with a device/emulator connected.
- **Debug Keystore**: a valid Android debug keystore (default: `~/.android/debug.keystore`).

## Usage

Run the script using `python3 app_generator/build_app.py`.

### Basic Command

```bash
python3 app_generator/build_app.py <output_directory> --start <N> --end <M>
```

### Examples

**1. Build apps 1 to 10 and save them to a folder named `test_apps`:**
```bash
python3 app_generator/build_app.py test_apps --start 1 --end 10
```

**2. Build apps 1 to 5 and automatically install them on the connected device:**
```bash
python3 app_generator/build_app.py test_install --start 1 --end 5 --install
```

**3. Use more parallel workers for faster builds:**
```bash
python3 app_generator/build_app.py test_apps --start 1 --end 600 --workers 8
```

### Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `output_dir` | Directory where generated APKs will be saved. | Required |
| `--start` | The starting application number. | `1` |
| `--end` | The ending application number. | Required |
| `--install` | If present, installs the APK via `adb` after building. | `False` |
| `--workers` | Number of parallel processes to use. | CPU Count |
| `--config` | Toolchain config file. | `config.local.toml` lookup |

## Configuration

Machine-specific settings live in `config.local.toml`, which is **not committed**. Start from the template:

```bash
cp config.example.toml config.local.toml
```

Every key is optional. For each key, the config file wins, then environment variables (`ANDROID_HOME`/`ANDROID_SDK_ROOT`, `JAVA_HOME`), then auto-detection (`~/Android/Sdk`, newest complete build-tools, tools on `PATH`). The file is looked up as `--config PATH` > `$APKGEN_CONFIG` > `./config.local.toml` > `<repo>/config.local.toml` > `$XDG_CONFIG_HOME/apkgen/config.toml`.

Before building, the script checks every tool and file and, if anything is missing, lists all problems and exits with status 2.
