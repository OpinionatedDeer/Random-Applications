"""adb helpers. Every call checks its result; nothing fails silently."""
import os
import re
import shlex
import subprocess


class AdbError(Exception):
    """An adb command failed or timed out. Holds only a string so it pickles."""

    def __reduce__(self):
        return (AdbError, self.args)


def _tail(text, lines=10):
    return "\n".join(text.strip().splitlines()[-lines:])


def run(tc, args, *, serial=None, timeout=60):
    cmd = [tc.adb] + (["-s", serial] if serial else []) + list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AdbError(f"timed out after {timeout}s: {' '.join(cmd)}") from None
    except OSError as e:
        raise AdbError(f"cannot run adb: {e}") from None


def devices(tc):
    """[(serial, state)] from `adb devices`."""
    result = run(tc, ["devices"], timeout=30)
    if result.returncode != 0:
        raise AdbError(f"adb devices failed: {_tail(result.stderr or result.stdout)}")
    rows = []
    for line in result.stdout.splitlines()[1:]:
        serial, sep, state = line.partition("\t")  # states can be several words ("no permissions ...")
        if sep and serial.strip():
            rows.append((serial.strip(), state.strip()))
    return rows


def preflight(tc, serial=None):
    """Start the adb server and pick exactly one ready device. Returns its serial."""
    result = run(tc, ["start-server"], timeout=60)
    if result.returncode != 0:
        raise AdbError(f"adb start-server failed: {_tail(result.stderr or result.stdout)}")
    serial = serial or os.environ.get("ANDROID_SERIAL") or None
    rows = devices(tc)
    ready = [s for s, state in rows if state == "device"]
    if serial:
        if serial not in ready:
            states = dict(rows)
            raise AdbError(f"device {serial} is not ready (state: {states.get(serial, 'not connected')})")
        return serial
    if len(ready) == 1:
        return ready[0]
    if not ready:
        listing = ", ".join(f"{s} ({state})" for s, state in rows) or "none"
        raise AdbError(f"no ready adb device (seen: {listing})")
    raise AdbError(f"several devices connected ({', '.join(ready)}); choose one with --serial or ANDROID_SERIAL")


def install(tc, apk, serial, timeout=180):
    result = run(tc, ["install", "-r", apk], serial=serial, timeout=timeout)
    if result.returncode != 0 or "Success" not in result.stdout:
        raise AdbError(_tail(result.stdout + "\n" + result.stderr) or f"exit {result.returncode}")


def launch(tc, am_args, serial, timeout=60):
    """`am start -W`; succeeds only when am reports `Status: ok`."""
    command = shlex.join(["am", "start", "-W", *am_args])  # adb shell joins words unquoted
    result = run(tc, ["shell", command], serial=serial, timeout=timeout)
    output = result.stdout + result.stderr
    errors = [line for line in output.splitlines() if line.startswith("Error")]
    if result.returncode != 0 or errors or "Status: ok" not in output:
        raise AdbError(_tail(output) or f"exit {result.returncode}")


def shell(tc, script, serial, timeout=600):
    """Run a device-side shell script; returns stdout. Raises on a non-zero exit."""
    result = run(tc, ["shell", script], serial=serial, timeout=timeout)
    if result.returncode != 0:
        raise AdbError(_tail(result.stderr or result.stdout) or f"exit {result.returncode}")
    return result.stdout


def list_packages(tc, serial):
    out = shell(tc, "pm list packages", serial, timeout=120)
    return {line[len("package:"):].strip() for line in out.splitlines() if line.startswith("package:")}


def uninstall_many(tc, packages, serial, chunk=200):
    """Uninstall packages in batches (one adb round-trip per batch). Returns (removed, failed)."""
    removed, failed = [], []
    packages = sorted(packages)
    for start in range(0, len(packages), chunk):
        batch = packages[start:start + chunk]
        script = ("for p in %s; do cmd deviceidle whitelist -$p >/dev/null 2>&1; "
                  "if pm uninstall $p >/dev/null 2>&1; then echo OK:$p; else echo FAIL:$p; fi; done"
                  % " ".join(batch))
        out = shell(tc, script, serial)
        done = {}
        for line in out.splitlines():
            status, _, pkg = line.strip().partition(":")
            done[pkg] = status
        removed += [p for p in batch if done.get(p) == "OK"]
        failed += [p for p in batch if done.get(p) != "OK"]
    return removed, failed


def broadcast_many(tc, packages, receiver_class, am_args, serial, *, skip_stopped=False, chunk=100):
    """Send an explicit broadcast to <package>/<receiver_class> for each package, batched in
    device-side loops. Returns {package: result data ('' if none)} for every package whose
    receiver answered; packages missing from the result got no reply.

    Delivering a broadcast takes an app out of the stopped state (and on Android 15+ the system
    then sends it BOOT_COMPLETED), so skip_stopped=True leaves force-stopped apps untouched and
    reports them as STOPPED_REPLY instead; otherwise stopped apps are included (flag 0x20)."""
    replies = {}
    args = shlex.join((["-f", "0x20"] if not skip_stopped else []) + list(am_args))
    done = re.compile(r'Broadcast completed: result=-?\d+(?:, data="(.*)")?')
    check = ('if dumpsys package "$p" | grep -q " stopped=true"; then echo "@@STOPPED"; else %s; fi'
             if skip_stopped else "%s")
    packages = list(packages)
    for start in range(0, len(packages), chunk):
        batch = packages[start:start + chunk]
        send = 'am broadcast -n "$p/%s" %s 2>&1' % (receiver_class, args)
        # `; true`: one failing am must not abort the batch or discard the replies collected.
        script = ('for p in %s; do echo "@@$p"; %s; done; true'
                  % (" ".join(shlex.quote(p) for p in batch), check % send))
        current = None
        for line in shell(tc, script, serial).splitlines():
            if line.startswith("@@STOPPED") and current:
                replies[current] = STOPPED_REPLY
            elif line.startswith("@@"):
                current = line[2:].strip()
            elif current and (m := done.search(line)):
                replies[current] = m.group(1) or ""
    return replies


STOPPED_REPLY = "stopped (force-stopped: not switching; launch it or run `apkgen signal auto`)"
