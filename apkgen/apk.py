"""Build a signed APK from an ApkSpec using the raw SDK tools (no Gradle).

Pipeline: aapt2 compile -> aapt2 link -> javac + d8 (or a prebuilt dex) -> zip -> zipalign
-> apksigner.
"""
import ctypes
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ERROR_TAIL_LINES = 20


class BuildError(Exception):
    """A build step failed. Holds only strings so it pickles across processes."""

    def __init__(self, step, message):
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message

    def __reduce__(self):
        return (BuildError, (self.step, self.message))


@dataclass(frozen=True)
class ApkSpec:
    package: str                                  # applicationId; output is OUT/{package}.apk
    manifest: str                                 # AndroidManifest.xml text
    resources: Mapping[str, str | bytes]          # path under res/ -> content
    java_sources: Mapping[str, str] = field(default_factory=dict)  # path under src/ -> text
    dex: str | None = None                        # prebuilt classes.dex used instead of java_sources
    launch: tuple[str, ...] | None = None         # arguments for `adb shell am start -W`
    post_install: tuple[tuple[str, ...], ...] = ()  # device shell commands run after installing


def _die_with_parent():
    # Linux: the kernel kills the tool if the worker that started it dies (OOM kill, or the
    # SIGTERM concurrent.futures sends to the other workers), so no orphaned javac/d8 keeps
    # writing into the scratch directory.
    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL)  # 1 = PR_SET_PDEATHSIG


def _redact(cmd):
    """Command line for error messages, without the keystore password."""
    words = [str(c) for c in cmd]
    for i, word in enumerate(words[:-1]):
        if word in ("--ks-pass", "--key-pass") and words[i + 1].startswith("pass:"):
            words[i + 1] = "pass:***"
    return " ".join(words)


def run(step, cmd, *, env=None):
    result = subprocess.run([str(c) for c in cmd], env=env, capture_output=True, text=True,
                            preexec_fn=_die_with_parent if sys.platform.startswith("linux") else None)
    if result.returncode != 0:
        output = (result.stderr.strip() or result.stdout.strip()).splitlines()
        raise BuildError(step, "command failed (exit %d): %s\n%s" % (
            result.returncode, _redact(cmd), "\n".join(output[-ERROR_TAIL_LINES:])))
    return result.stdout


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def compile_dex(java_sources, tc, workdir, *, min_api=None, bootclasspath=False):
    """Compile Java sources to dex. Returns the list of produced classes*.dex paths.

    bootclasspath=True compiles against android.jar instead of the JDK's own classes, so
    APIs that exist only in the desktop JDK fail at compile time instead of on the device.
    """
    if not java_sources:
        raise BuildError("javac", "no Java sources")
    work = Path(workdir)
    src_files = []
    for rel, text in java_sources.items():
        path = work / "src" / rel
        _write(path, text)
        src_files.append(path)
    classes = work / "classes"
    javac = [tc.javac, "-source", "8", "-target", "8", "-Xlint:-options"]
    if bootclasspath:
        javac += ["-bootclasspath", tc.android_jar]
    run("javac", javac + ["-cp", tc.android_jar, "-d", classes] + src_files)

    class_files = sorted(classes.rglob("*.class"))
    if not class_files:
        raise BuildError("javac", "no class files produced")
    dex_dir = work / "dex"
    dex_dir.mkdir()
    d8 = [tc.d8, "--lib", tc.android_jar, "--output", dex_dir]
    if min_api is not None:
        d8 += ["--min-api", str(min_api)]
    run("d8", d8 + class_files, env=tc.tool_env())
    dex_files = sorted(dex_dir.glob("classes*.dex"))
    if not dex_files:
        raise BuildError("d8", "classes.dex not produced")
    return dex_files


def build_apk(spec, tc, out_dir, workdir):
    """Build, align and sign spec into out_dir. workdir must not exist yet and must be on
    the same filesystem as out_dir (the signed files are moved into place with os.replace).
    Returns the path of the final APK."""
    work = Path(workdir)
    work.mkdir()  # no parents: if the run's scratch dir is gone, fail instead of recreating it

    for rel, content in spec.resources.items():
        _write(work / "res" / rel, content)
    manifest = work / "AndroidManifest.xml"
    _write(manifest, spec.manifest)

    flata = work / "res.flata"
    run("aapt2 compile", [tc.aapt2, "compile", "--dir", work / "res", "-o", flata])
    base_apk = work / "base.apk"
    run("aapt2 link", [tc.aapt2, "link", "--manifest", manifest, "-o", base_apk,
                       "-I", tc.android_jar, flata])

    if spec.dex:
        dex_files = [spec.dex]
    else:
        dex_files = compile_dex(spec.java_sources, tc, work / "java")
    run("zip", [tc.zip, "-uj", base_apk] + dex_files)

    aligned_apk = work / "aligned.apk"
    run("zipalign", [tc.zipalign, "-p", "4", base_apk, aligned_apk])
    signed_apk = work / "signed.apk"
    run("apksigner", [tc.apksigner, "sign", "--ks", tc.keystore, "--ks-pass", tc.keystore_pass,
                      "--out", signed_apk, aligned_apk], env=tc.tool_env())

    final_apk = Path(out_dir) / f"{spec.package}.apk"
    idsig, final_idsig = Path(f"{signed_apk}.idsig"), Path(f"{final_apk}.idsig")
    os.replace(signed_apk, final_apk)
    if idsig.exists():
        os.replace(idsig, final_idsig)
    else:
        final_idsig.unlink(missing_ok=True)  # never leave a stale signature next to a new APK
    return str(final_apk)
