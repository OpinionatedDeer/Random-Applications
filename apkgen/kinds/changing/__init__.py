"""Icon-switching test apps: the launcher icon changes on the device over time.

Each app has frame aliases .Icon0 .. .Icon<N-1> plus .IconInit, all pointing at one invisible
EntryActivity. The shared Java runtime (java/, package RUNTIME_PKG) enables one alias at a
time on a wall-clock schedule, so the launcher receives PACKAGE_CHANGED and has to refresh
the icon it shows. The runtime is identical for every app: prepare() compiles it once per run
and every APK reuses that classes.dex; per-app values go into manifest meta-data.
"""
import sys
from dataclasses import dataclass
from importlib import resources

from ... import icons, templating
from ...apk import ApkSpec, BuildError, compile_dex

HELP = "icon-switching test apps (com.test.iconswitch.app<N>)"
PACKAGE_PREFIX = "com.test.iconswitch.app"
RUNTIME_PKG = "com.test.iconswitch.runtime"
ACTION_PREFIX = "com.test.iconswitch.action."    # must match Config.java
SIGNAL_ACTIONS = ("switch", "auto", "stop", "reset", "status")
MIN_FRAMES, MAX_FRAMES = 2, 36
MIN_INTERVAL_S = 10
MAX_INTERVAL_S = 7 * 24 * 3600   # keeps interval_ms within a 32-bit meta-data integer
INIT_COLOUR = (32, 32, 32)
APP_COLOUR = (128, 128, 128)
GOLDEN = 0.6180339887498949       # stagger: low-discrepancy phase per app number


@dataclass(frozen=True)
class Options:
    frames: int
    interval_s: int
    phase: str          # "sync" | "stagger"
    label_mode: str     # "same" | "frame"
    wakeup: bool
    whitelist: bool


def add_arguments(parser):
    g = parser.add_argument_group("icon switching")
    g.add_argument("--frames", type=int, default=6,
                   help=f"number of icons to cycle through, {MIN_FRAMES}-{MAX_FRAMES} (default: 6)")
    g.add_argument("--interval", type=int, default=60,
                   help=f"seconds between switches, at least {MIN_INTERVAL_S} (default: 60)")
    g.add_argument("--phase", choices=("sync", "stagger"), default="sync",
                   help="sync: all apps switch at the same moment (default); "
                        "stagger: each app gets its own offset within the interval")
    g.add_argument("--label-mode", choices=("same", "frame"), default="same",
                   help="same: only the icon changes (default); frame: the label changes too")
    g.add_argument("--wakeup", action="store_true",
                   help="wake the device for switches (RTC_WAKEUP + allow-while-idle alarms); "
                        "costs battery on a real phone until the apps are stopped or removed")
    g.add_argument("--whitelist", action="store_true",
                   help="exempt each app from battery optimisation after installing "
                        "(requires --install or --launch)")


def options_from_args(args):
    if not MIN_FRAMES <= args.frames <= MAX_FRAMES:
        raise ValueError(f"--frames must be between {MIN_FRAMES} and {MAX_FRAMES}")
    if not MIN_INTERVAL_S <= args.interval <= MAX_INTERVAL_S:
        raise ValueError(f"--interval must be between {MIN_INTERVAL_S} and {MAX_INTERVAL_S} seconds")
    if args.whitelist and not (args.install or args.launch):
        raise ValueError("--whitelist requires --install or --launch")
    count = args.end - args.start + 1
    if args.phase == "sync" and args.interval < count:
        print(f"warning: {count} apps switching together every {args.interval} s may fall behind; "
              f"consider --interval {count} or more, or --phase stagger", file=sys.stderr)
    if args.wakeup and count > 20:
        print(f"warning: --wakeup with {count} apps wakes the device about {count} times every "
              f"{args.interval} s, also after reboots, until `apkgen signal stop` or "
              f"`apkgen uninstall --kind changing`", file=sys.stderr)
    return Options(frames=args.frames, interval_s=args.interval, phase=args.phase,
                   label_mode=args.label_mode, wakeup=args.wakeup, whitelist=args.whitelist)


def runtime_sources():
    """{path under src/: text} for every .java file shipped in java/."""
    sources = {}

    def walk(node, rel):
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            if child.is_dir():
                walk(child, f"{rel}{child.name}/")
            elif child.name.endswith(".java"):
                sources[rel + child.name] = child.read_text(encoding="utf-8")

    walk(resources.files(__name__).joinpath("java"), "")
    return sources


def prepare(tc, opts, workdir):
    """Compile the shared runtime once; returns the path of its classes.dex."""
    dex_files = compile_dex(runtime_sources(), tc, workdir, min_api=24, bootclasspath=True)
    if len(dex_files) != 1:
        raise BuildError("d8", f"expected one dex file for the runtime, got {len(dex_files)}")
    return str(dex_files[0])


def labels(i, opts):
    """(app_name, init label, [frame labels])."""
    name = f"Switch App {i}"
    if opts.label_mode == "same":
        return name, name, [name] * opts.frames
    return name, f"S{i} init", [f"S{i} f{k}" for k in range(opts.frames)]


def phase_ms(i, opts):
    """sync: 0. stagger: an offset that depends only on the app number (golden-ratio sequence),
    so any range of apps is spread roughly evenly and separate batches stay consistent."""
    if opts.phase == "sync":
        return 0
    return int((i * GOLDEN) % 1.0 * opts.interval_s * 1000)


def make_spec(i, opts, tc, prepared):
    package = f"{PACKAGE_PREFIX}{i}"
    interval_ms = opts.interval_s * 1000
    aliases = "".join(templating.render(__name__, "alias.xml.tmpl", k=k, rt=RUNTIME_PKG)
                      for k in range(opts.frames))
    manifest = templating.render(
        __name__, "AndroidManifest.xml.tmpl", package=package, rt=RUNTIME_PKG, app=i,
        frames=opts.frames, interval_ms=interval_ms, phase_ms=phase_ms(i, opts),
        wakeup="true" if opts.wakeup else "false", aliases=aliases)

    app_name, label_init, frame_labels = labels(i, opts)
    strings = templating.render(
        __name__, "strings.xml.tmpl", app_name=templating.aapt_string(app_name),
        label_init=templating.aapt_string(label_init),
        labels="".join(f'    <string name="label_{k}">{templating.aapt_string(text)}</string>\n'
                       for k, text in enumerate(frame_labels)))

    res = {
        "values/strings.xml": strings,
        icons.drawable_path("icon_app"): icons.render_caption_icon(i, "APP", APP_COLOUR, tc.font),
        icons.drawable_path("icon_init"): icons.render_caption_icon(i, "INIT", INIT_COLOUR, tc.font),
    }
    for k in range(opts.frames):
        res[icons.drawable_path(f"icon_{k}")] = icons.render_frame_icon(i, k, opts.frames, tc.font)

    return ApkSpec(
        package=package,
        manifest=manifest,
        resources=res,
        dex=prepared,
        launch=("-f", "0x10000", "-n", f"{package}/{RUNTIME_PKG}.EntryActivity",
                "--ez", "bootstrap", "true"),
        post_install=post_install(package, opts),
    )


def post_install(package, opts):
    """Device commands after each install: optional battery exemption, then a RESTORE broadcast
    that resumes the saved mode and repairs the alias state. Unlike MY_PACKAGE_REPLACED it also
    reaches force-stopped apps (0x20 = FLAG_INCLUDE_STOPPED_PACKAGES)."""
    commands = []
    if opts.whitelist:
        commands.append(("cmd", "deviceidle", "whitelist", f"+{package}"))
    commands.append(("am", "broadcast", "-f", "0x20", "-n", f"{package}/{RUNTIME_PKG}.SwitchReceiver",
                     "-a", ACTION_PREFIX + "RESTORE"))
    return tuple(commands)
