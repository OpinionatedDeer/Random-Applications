"""Command-line interface: python -m apkgen <command> ..."""
import argparse
import multiprocessing
import os
import re
import signal
import sys

from . import adb, bulk
from .adb import AdbError
from .config import ConfigError, doctor_report, resolve, resolve_adb
from .kinds import KINDS


def _toolchain(args, need_adb=False, adb_only=False):
    """Resolve the toolchain or print every problem and return None."""
    try:
        tc = resolve_adb(args.config) if adb_only else resolve(args.config, need_adb=need_adb)
    except ConfigError as e:
        print(f"apkgen: {e}", file=sys.stderr)
        return None
    print(f"config: {tc.config_path or 'none (auto-detect)'}", file=sys.stderr)
    for warning in tc.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return tc


def _device(tc, serial):
    try:
        return adb.preflight(tc, serial)
    except AdbError as e:
        print(f"apkgen: adb: {e}", file=sys.stderr)
        return None


def cmd_build(args):
    kind = bulk.kind_module(args.kind)
    if args.start < 0 or args.end < args.start:
        print(f"apkgen: invalid range --start {args.start} --end {args.end}", file=sys.stderr)
        return 2
    if args.workers < 1:
        print("apkgen: --workers must be at least 1", file=sys.stderr)
        return 2
    try:
        opts = kind.options_from_args(args)
    except ValueError as e:
        print(f"apkgen: {e}", file=sys.stderr)
        return 2
    install = args.install or args.launch
    tc = _toolchain(args, need_adb=install)
    if tc is None:
        return 2
    serial = None
    if install:
        serial = _device(tc, args.serial)
        if serial is None:
            return 2
    indices = range(args.start, args.end + 1)
    workers = min(args.workers, len(indices))
    print(f"Starting build of {len(indices)} apps (from {args.start} to {args.end}) "
          f"with {workers} workers...", flush=True)
    return bulk.run(args.kind, opts, tc, indices, args.output_dir, workers=workers,
                    install=install, launch=args.launch, serial=serial)


def cmd_doctor(args):
    lines, ok, tc = doctor_report(args.config)
    print("\n".join(lines))
    if tc and tc.adb and os.access(tc.adb, os.X_OK):
        try:
            rows = adb.devices(tc)
            print("adb devices: " + (", ".join(f"{s} ({state})" for s, state in rows) or "none"))
        except AdbError as e:
            print(f"adb devices: {e}")
    return 0 if ok else 2


def cmd_uninstall(args):
    tc = _toolchain(args, adb_only=True)
    if tc is None:
        return 2
    serial = _device(tc, args.serial)
    if serial is None:
        return 2
    kinds = KINDS if args.kind == "all" else (args.kind,)
    patterns = [re.compile(re.escape(bulk.kind_module(k).PACKAGE_PREFIX) + r"\d+") for k in kinds]
    try:
        packages = [p for p in adb.list_packages(tc, serial) if any(rx.fullmatch(p) for rx in patterns)]
        if not packages:
            print(f"Nothing to uninstall ({', '.join(kinds)}).")
            return 0
        print(f"Uninstalling {len(packages)} apps from {serial}...", flush=True)
        removed, failed = adb.uninstall_many(tc, packages, serial)
    except AdbError as e:
        print(f"apkgen: adb: {e}", file=sys.stderr)
        return 1
    for p in failed:
        print(f"Failed to uninstall {p}")
    print(f"{len(removed)} removed, {len(failed)} failed")
    return 1 if failed else 0


def _common(parser):
    parser.add_argument("--config", help="toolchain config file (default: config.local.toml lookup)")


def _build_parser(sub, name, kind):
    p = sub.add_parser(name, help=kind.HELP, description=f"Build {kind.HELP}.")
    p.add_argument("output_dir", nargs="?", default="apps_output",
                   help="directory for the APKs (default: apps_output)")
    p.add_argument("--start", type=int, default=1, help="first app number (default: 1)")
    p.add_argument("--end", type=int, required=True, help="last app number")
    p.add_argument("--workers", type=int, default=multiprocessing.cpu_count(),
                   help="parallel build processes (default: CPU count)")
    p.add_argument("--install", action="store_true", help="install each APK with adb after building")
    p.add_argument("--launch", action="store_true", help="launch each app after installing (implies --install)")
    p.add_argument("--serial", help="adb device serial (default: $ANDROID_SERIAL or the only device)")
    _common(p)
    kind.add_arguments(p)
    p.set_defaults(func=cmd_build, kind=name)


def make_parser():
    parser = argparse.ArgumentParser(prog="apkgen", description="Generate Android launcher test apps without Gradle.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name in KINDS:
        _build_parser(sub, name, bulk.kind_module(name))

    p = sub.add_parser("doctor", help="show the resolved toolchain and check it")
    _common(p)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("uninstall", help="remove generated apps from the device")
    p.add_argument("--kind", choices=KINDS + ("all",), default="all", help="which apps to remove (default: all)")
    p.add_argument("--serial", help="adb device serial (default: $ANDROID_SERIAL or the only device)")
    _common(p)
    p.set_defaults(func=cmd_uninstall)
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    # Closing the terminal or `timeout`/`kill` take the same cleanup path as Ctrl-C.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.default_int_handler)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # Output piped into e.g. `head` that exited: stop quietly (see Python's SIGPIPE notes).
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
