# apkgen: Android launcher test-app generator

Builds any number of small, unique Android apps for testing launchers: performance with
hundreds of apps, icon loading and caching. It skips Gradle entirely and drives the SDK
tools directly (`javac` → `aapt2` → `d8` → `zip` → `zipalign` → `apksigner`), so building
hundreds of APKs takes seconds per batch, in parallel.

- **Normal apps** (`apkgen normal`): `com.test.app.app<N>`, labelled "Test App N". Each icon shows its number on a colour derived from N.
- **Parallel builds**, with optional `adb install` and launch, a per-app result line, and a summary. The exit code is non-zero if anything failed.
- **Machine-specific paths** live in an uncommitted `config.local.toml`.

## Setup

Requirements:
- Python 3.11+ with Pillow (`pip install Pillow`)
- A JDK (`javac`, `java`)
- An Android SDK with build-tools (any recent version) and the `android-30` platform
- `zip`
- `adb` (only for installing)

```bash
cp config.example.toml config.local.toml   # edit if your paths differ; every key is optional
make doctor                                # shows every resolved path and where it came from
```

## Usage

Run from the repository root; no installation is needed.

```bash
python3 -m apkgen normal --end 10                    # apps 1..10 into ./apps_output
python3 -m apkgen normal my_apps --start 1 --end 600 --workers 8
python3 -m apkgen normal --end 50 --install          # build, then adb install each one
python3 -m apkgen normal --end 5 --launch            # install, then open each app once
python3 -m apkgen uninstall                          # remove every generated app from the device
```

| Option | Meaning | Default |
| :--- | :--- | :--- |
| `output_dir` | Where APKs go (`<package>.apk` plus apksigner's `.apk.idsig`). | `apps_output` |
| `--start`, `--end` | Range of app numbers. | `1`, required |
| `--workers` | Parallel build processes. | CPU count |
| `--install` | `adb install -r` each APK. Failures are reported. | off |
| `--launch` | Also open each app once after install (implies `--install`). | off |
| `--serial` | adb device to use. | `$ANDROID_SERIAL`, or the only device |
| `--config` | Toolchain config file. | lookup, see below |

`uninstall --kind normal|all` lists the device's packages once and removes matching ones in batches.

### Makefile shortcuts

```bash
make build END=10 DIR=my_apps
make build END=5 INSTALL=1        # or LAUNCH=1, WORKERS=8, CONFIG=other.toml
make install END=5
make uninstall
make test
make clean DIR=my_apps
```

> `make clean` without `DIR` deletes `apps_output/`. It refuses to delete the repository,
> `$HOME`, any directory that contains either of them (such as `..` or `/`), and any
> directory containing `.git`.

## Configuration

`config.local.toml` is gitignored; `config.example.toml` documents every key:
`sdk_dir`, `build_tools`, `platform`, `javac`, `java`, `zip`, `adb`, `keystore`,
`keystore_pass` and `font`.

**Where a value comes from.** For each key the first source that provides a value wins:
1. the config file
2. environment: `ANDROID_HOME`/`ANDROID_SDK_ROOT` for the SDK, `JAVA_HOME` for javac and java
3. auto-detection:
   - SDK: `~/Android/Sdk`
   - build-tools: the newest version that contains all four tools
   - platform: `android-30`
   - other tools: found on `PATH`
   - keystore: `~/.android/debug.keystore`
   - font: common Liberation and DejaVu locations

**Which config file is used:** `--config PATH` > `$APKGEN_CONFIG` > `./config.local.toml` >
`<repo>/config.local.toml` > `$XDG_CONFIG_HOME/apkgen/config.toml` > none.
- Every build prints the file it used.
- A file named with `--config` or `$APKGEN_CONFIG` must exist.
- Before building, every tool and file is checked. If anything is missing, all problems are listed and the exit status is 2.

Pinning `build_tools` and `platform` keeps the generated APK contents identical when newer
SDK packages are installed later. Only zip timestamps and signatures differ between builds.

## Development

```bash
make test                 # stdlib unittest; needs no SDK
```

Optional install, which provides an `apkgen` command (PEP 668 systems need a venv):

```bash
python3 -m venv --system-site-packages .venv && .venv/bin/pip install --no-deps -e .
```

Layout:

```
apkgen/
  cli.py         subcommands
  config.py      toolchain resolution
  apk.py         ApkSpec and build pipeline
  adb.py         device helpers
  bulk.py        parallel runner
  icons.py       icon rendering
  templating.py  template loading
  kinds/
    normal/      templates + make_spec() for normal apps
tests/           unit tests
```

A new kind of app is a subpackage of `apkgen/kinds/` that provides `HELP`,
`PACKAGE_PREFIX`, `add_arguments`, `options_from_args`, `make_spec` and, optionally,
`prepare`. Add it to `KINDS` (see `apkgen/kinds/__init__.py`).

The normal kind reproduces the original generator's output exactly: the same entries,
icons and line numbers, which are compiled into the APK. `tests/test_templating.py` guards
this.
