# apkgen: Android launcher test-app generator

Builds any number of small, unique Android apps for testing launchers: performance with
hundreds of apps, icon loading, and icon-cache invalidation. It skips Gradle entirely and drives the SDK
tools directly (`javac` → `aapt2` → `d8` → `zip` → `zipalign` → `apksigner`), so building
hundreds of APKs takes seconds per batch, in parallel.

- **Normal apps** (`apkgen normal`): `com.test.app.app<N>`, labelled "Test App N". Each icon shows its number on a colour derived from N.
- **Icon-switching apps** (`apkgen changing`): `com.test.iconswitch.app<N>`. Each app changes its own launcher icon on the device at a fixed interval. Any number of them can be installed next to any number of normal apps.
- **Icons** are 512×512 PNGs in `res/drawable-xxxhdpi/`: sharp, but decoded at a normal size.
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
python3 -m apkgen changing --end 20 --launch         # 20 icon-switching apps, started
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
| `--legacy-icons` | Normal apps only: put the icon in `res/drawable/` like the original generator. Android then treats it as mdpi and decodes it about 4× larger. | off |

`uninstall --kind normal|changing|all` lists the device's packages once and removes matching ones in batches.

## Icon-switching apps

Each `changing` app declares one invisible entry activity and N+1 launcher
`activity-alias` entries:
- `.IconInit` (an "INIT" icon), enabled at install
- `.Icon0` … `.Icon<N-1>` (frame icons), disabled at install

A shared runtime enables exactly one alias at a time. It enables the new alias first, then
disables the old one, so the launcher never sees zero entries. The launcher gets
`PACKAGE_CHANGED` and must reload the icon.

**Which frame is shown.** The frame comes from the wall clock,
`frame = ((now − phase) / interval) % N`, so the expected icon at any moment is known
on the host too. Switches are driven by exact alarms, one per interval.

**What the icons look like.** Frame icons share a hue per frame, the same in every app in
`sync` mode. Each shows a ring with the current segment filled, the app number, and `f<k>`.
A stale icon is the one whose colour differs from its neighbours.

```bash
# 300 normal + 20 switching apps, sharing apps_output/
python3 -m apkgen normal --end 300 --install
python3 -m apkgen changing --end 20 --interval 60 --launch --whitelist
```

**Switching starts only when you start it.** Freshly installed apps show their INIT icon and
stay dormant. To start them, use any of these:
- `--launch`, which opens each app's entry activity once (it finishes immediately). This
  runs one app at a time, about 0.1 s per app.
- `apkgen signal auto` after `--install`. This is a batched broadcast and much faster for
  hundreds of apps; combine it with `--whitelist` so app standby doesn't defer the first alarms.
- Tapping the app in the launcher.

**After a reinstall or a force-stop:**
- After every install, `apkgen` sends a RESTORE broadcast, so a reinstall continues the saved
  mode. This works even after a force-stop or with a different `--frames`.
- A force-stopped app stops switching until it is launched again or receives a `signal`
  other than `status`.

| Option | Meaning | Default |
| :--- | :--- | :--- |
| `--frames N` | Number of icons to cycle through (2–36). | `6` |
| `--interval S` | Seconds between switches (at least 10). | `60` |
| `--phase sync\|stagger` | `sync`: every app switches at the same moment, a burst of `onPackageChanged` and same-colour icons. `stagger`: each app gets a fixed offset within the interval, based only on its number, so separate batches stay spread out. | `sync` |
| `--label-mode same\|frame` | `same`: only the icon changes. `frame`: the label changes too ("S7 f2"), which helps tell an ignored update from a stale bitmap. | `same` |
| `--wakeup` | Use `RTC_WAKEUP` allow-while-idle alarms so switches continue while the device sleeps. Each app wakes the device once per interval, also after reboots, until `signal stop` or uninstall. Avoid on a phone you rely on for battery. | off |
| `--whitelist` | `cmd deviceidle whitelist +pkg` after install, so app standby doesn't defer alarms. Needs `--install` or `--launch`. | off |

**Control installed switchers** with `signal`. It sends one explicit broadcast per app and
prints each app's status:

```bash
python3 -m apkgen signal status                   # mode, enabled alias, expected alias, next switch
python3 -m apkgen signal switch --index 2         # hold every app on frame 2 (K < --frames)
python3 -m apkgen signal switch                   # hold the next frame
python3 -m apkgen signal auto                     # resume the clock
python3 -m apkgen signal stop                     # hold the current frame
python3 -m apkgen signal reset --start 1 --end 5  # back to the INIT icon, no alarm
```

For a single app, the same broadcast is
`adb shell am broadcast -n com.test.iconswitch.app1/com.test.iconswitch.runtime.SwitchReceiver -a com.test.iconswitch.action.SWITCH --ei index 2`.

**Checking for stale icons**
- **Watch the switches:** `adb logcat -s IconSwitcher` logs every switch, with `from`, `to` and `lateMs`.
- **Deterministic check:** `signal switch --index K`, wait a few seconds, then screenshot (`adb exec-out screencap -p > shot.png`). Every switching icon should now have frame K's colour.
  - Android batches `PACKAGE_CHANGED`, so allow roughly 1–10 s before calling an icon stale.
- **Dashboard:** tapping an app opens a dashboard showing the icon PackageManager reports, the enabled alias versus the clock's expected alias (with a MISMATCH flag), and buttons for the same controls.
- **Control baseline:** stock Launcher3 follows every switch. Comparing against it separates a launcher bug from a test-app problem.

`status` leaves force-stopped apps alone and reports them as stopped. An out-of-range
`--index` is reported as an error, and the command exits 1.

**Cleanup.** Switchers keep running, and resume after reboots, until you stop them:
- `signal stop` freezes all switchers.
- `uninstall --kind changing` removes them and their battery-optimisation exemptions. Do this
  after testing on a physical device.

**Caveats**
- Doze defers non-wakeup alarms while the screen is off. The emulator runs never exercised
  standby or Doze, so on a real phone use `--whitelist`.
- Clock changes re-sync immediately (`TIME_SET`).
- A switch that happens a few seconds before a boundary, for example from `signal auto`, can
  make the next one up to ~5 s late. That's AlarmManager's minimum delay.
- With many apps in `sync`, use an interval of at least as many seconds as there are apps; `apkgen` warns otherwise.
- OEM battery managers can block alarms. An AOSP emulator or a Pixel behaves predictably.

### Makefile shortcuts

```bash
make build END=10 DIR=my_apps
make build END=5 INSTALL=1        # or LAUNCH=1, WORKERS=8, LEGACY_ICONS=1, CONFIG=other.toml
make install END=5
make changing END=20 LAUNCH=1 WHITELIST=1 INTERVAL=60 FRAMES=6 PHASE=stagger
make signal ACTION=switch INDEX=2
make uninstall                    # KIND=normal|changing|all
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
    changing/    templates, prepare() and make_spec() for icon-switching apps
      java/      shared Android runtime (com.test.iconswitch.runtime), compiled once per run
tests/           unit tests
```

A new kind of app is a subpackage of `apkgen/kinds/` that provides `HELP`,
`PACKAGE_PREFIX`, `add_arguments`, `options_from_args`, `make_spec` and, optionally,
`prepare`. Add it to `KINDS` (see `apkgen/kinds/__init__.py`).

With `--legacy-icons`, the normal kind reproduces the original generator's output exactly:
the same entries, icons and line numbers, which are compiled into the APK.
`tests/test_templating.py` guards this.

The changing kind's runtime may only use APIs available at API 24, its `minSdkVersion`. It
must not reference `R`, because one dex is shared by every app. `tests/test_manifest.py`
checks the manifest rules that aapt2 doesn't check, such as fully qualified component names
and declaration order.
