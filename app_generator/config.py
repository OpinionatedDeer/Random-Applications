"""Toolchain configuration.

Machine-specific paths (Android SDK, JDK, keystore, font) are resolved from, in order of
precedence for each key:

1. a TOML config file (``[toolchain]`` table), found via ``--config``, ``$APKGEN_CONFIG``,
   ``./config.local.toml``, ``<repo>/config.local.toml`` or ``$XDG_CONFIG_HOME/apkgen/config.toml``;
2. environment variables (``ANDROID_HOME``/``ANDROID_SDK_ROOT``, ``JAVA_HOME``);
3. auto-detection and defaults.

``resolve()`` checks everything up front and raises ``ConfigError`` listing every problem.
"""
import os
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG_NAME = "config.local.toml"
DEFAULT_PLATFORM = "android-30"
BUILD_TOOLS = ("aapt2", "d8", "zipalign", "apksigner")
KEYS = ("sdk_dir", "build_tools", "platform", "javac", "java", "zip", "adb",
        "keystore", "keystore_pass", "font")
PATH_KEYS = ("sdk_dir", "javac", "java", "zip", "adb", "keystore", "font")
FONT_CANDIDATES = (
    "/usr/share/fonts/liberation-fonts/LiberationSans-Bold.ttf",     # Gentoo
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",      # Fedora
    "/usr/share/fonts/TTF/LiberationSans-Bold.ttf",                  # Arch
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)


class ConfigError(Exception):
    def __init__(self, problems, config_path=None):
        self.problems = list(problems)
        self.config_path = config_path
        where = config_path or "none (auto-detect)"
        super().__init__("toolchain problems (config: %s)\n%s"
                         % (where, "\n".join("  - " + p for p in self.problems)))

    def __reduce__(self):
        return (ConfigError, (self.problems, self.config_path))


@dataclass(frozen=True)
class Toolchain:
    sdk_dir: str
    build_tools_dir: str
    android_jar: str
    aapt2: str
    d8: str
    zipalign: str
    apksigner: str
    javac: str
    java: str
    zip: str
    adb: str | None
    keystore: str
    keystore_pass: str
    font: str | None
    config_path: str | None
    warnings: tuple[str, ...] = ()

    def tool_env(self):
        """Environment for d8/apksigner, which are wrappers that run `java` from PATH."""
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(self.java) + os.pathsep + env.get("PATH", "")
        return env


def find_config(explicit=None, env=None):
    """Return the config file to use (a str) or None. Explicitly named files must exist."""
    env = os.environ if env is None else env
    for label, value in (("--config", explicit), ("$APKGEN_CONFIG", env.get("APKGEN_CONFIG"))):
        if value:
            path = Path(value).expanduser()
            if not path.is_file():
                raise ConfigError([f"config file given by {label} not found: {path}"], str(path))
            return str(path)
    xdg = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for path in (Path.cwd() / LOCAL_CONFIG_NAME, REPO_ROOT / LOCAL_CONFIG_NAME,
                 xdg / "apkgen" / "config.toml"):
        if path.is_file():
            return str(path)
    return None


def _load_file(path):
    """Read the [toolchain] table; return (values, problems)."""
    if path is None:
        return {}, []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        return {}, [f"{path}: invalid TOML: {e}"]
    except OSError as e:
        return {}, [f"{path}: cannot read: {e}"]
    problems = [f"{path}: unknown table or key '{k}' (expected a [toolchain] table)"
                for k in data if k != "toolchain"]
    table = data.get("toolchain", {})
    if not isinstance(table, dict):
        return {}, problems + [f"{path}: 'toolchain' must be a table"]
    problems += [f"{path}: unknown key toolchain.{k} (allowed: {', '.join(KEYS)})"
                 for k in table if k not in KEYS]
    values = {}
    base = Path(path).resolve().parent
    for key, value in table.items():
        if key not in KEYS:
            continue
        if not isinstance(value, str):
            problems.append(f"{path}: toolchain.{key} must be a string")
            continue
        if key in PATH_KEYS:
            p = Path(value).expanduser()
            value = str(p if p.is_absolute() else base / p)
        values[key] = value
    return values, problems


def _version_key(name):
    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-rc(\d+))?", name)
    if not m:
        return None
    return (tuple(int(x) for x in m.group(1).split(".")), m.group(2) is None, int(m.group(2) or 0))


def _is_exe(path):
    return path is not None and os.path.isfile(path) and os.access(path, os.X_OK)


def _newest_build_tools(sdk_dir):
    root = Path(sdk_dir) / "build-tools"
    if not root.is_dir():
        return None
    versions = [(k, d.name) for d in root.iterdir()
                if (k := _version_key(d.name)) and all(_is_exe(str(d / t)) for t in BUILD_TOOLS)]
    return max(versions)[1] if versions else None


class _Resolver:
    def __init__(self, config_path, env):
        self.env = env
        self.config_path = config_path
        self.file, self.problems = _load_file(config_path)
        self.rows = []  # (key, value, origin) for doctor output

    def pick(self, key, *candidates):
        """First non-empty candidate wins; candidates are (origin, value) pairs."""
        if key in self.file:
            self.rows.append((key, self.file[key], "config"))
            return self.file[key]
        for origin, value in candidates:
            if value:
                self.rows.append((key, value, origin))
                return value
        self.rows.append((key, None, "not found"))
        return None


def _resolve(config_path, env, need_adb):
    r = _Resolver(config_path, env)
    problems = r.problems
    warnings = []

    def env_path(var, *parts):
        return str(Path(env[var], *parts)) if env.get(var) else None

    default_sdk = Path.home() / "Android" / "Sdk"
    sdk = r.pick("sdk_dir", ("env ANDROID_HOME", env.get("ANDROID_HOME")),
                 ("env ANDROID_SDK_ROOT", env.get("ANDROID_SDK_ROOT")),
                 ("auto", str(default_sdk) if default_sdk.is_dir() else None))
    if sdk is None:
        problems.append("Android SDK not found: set toolchain.sdk_dir or ANDROID_HOME")
        sdk = ""
    elif not os.path.isdir(sdk):
        problems.append(f"sdk_dir is not a directory: {sdk}")

    bt_version = r.pick("build_tools", ("auto", _newest_build_tools(sdk) if sdk else None))
    bt_dir = os.path.join(sdk, "build-tools", bt_version or "?")
    if bt_version is None:
        problems.append(f"no build-tools with {', '.join(BUILD_TOOLS)} found under {sdk}/build-tools")
    tools = {t: os.path.join(bt_dir, t) for t in BUILD_TOOLS}
    if bt_version is not None:
        problems += [f"{t} not found or not executable: {p}" for t, p in tools.items() if not _is_exe(p)]

    platform = r.pick("platform", ("default", DEFAULT_PLATFORM))
    android_jar = os.path.join(sdk, "platforms", platform, "android.jar")
    if not os.path.isfile(android_jar):
        problems.append(f"android.jar not found: {android_jar} "
                        f"(install it with: sdkmanager \"platforms;{platform}\")")

    javac = r.pick("javac", ("env JAVA_HOME", env_path("JAVA_HOME", "bin", "javac")),
                   ("auto", shutil.which("javac")))
    if not _is_exe(javac):
        problems.append(f"javac not found or not executable: {javac}")
    # Look beside javac without resolving symlinks (distros route javac through wrapper scripts).
    beside = os.path.join(os.path.dirname(javac), "java") if javac else None
    java = r.pick("java", ("next to javac", beside if _is_exe(beside) else None),
                  ("env JAVA_HOME", env_path("JAVA_HOME", "bin", "java")),
                  ("auto", shutil.which("java")))
    if not _is_exe(java):
        problems.append(f"java not found or not executable: {java} (needed by d8 and apksigner)")

    zip_exe = r.pick("zip", ("auto", shutil.which("zip")))
    if not _is_exe(zip_exe):
        problems.append(f"zip not found or not executable: {zip_exe}")

    sdk_adb = os.path.join(sdk, "platform-tools", "adb")
    adb = r.pick("adb", ("auto", shutil.which("adb")), ("auto", sdk_adb if _is_exe(sdk_adb) else None))
    if need_adb and not _is_exe(adb):
        problems.append(f"adb not found or not executable: {adb} (needed for --install/--launch)")

    keystore = r.pick("keystore", ("default", str(Path.home() / ".android" / "debug.keystore")))
    if not os.path.isfile(keystore):
        problems.append(f"keystore not found: {keystore}")
    ks_pass = r.pick("keystore_pass", ("default", "pass:android"))
    if not re.match(r"^(pass|env|file):", ks_pass):
        problems.append("keystore_pass must use apksigner syntax: pass:..., env:VAR or file:PATH")

    font = r.pick("font", ("auto", next((f for f in FONT_CANDIDATES if os.path.isfile(f)), None)))
    if "font" in r.file and not os.path.isfile(font):
        problems.append(f"font not found: {font}")
    if font is None:
        warnings.append("no TrueType font found; icons use Pillow's built-in font")

    tc = Toolchain(sdk_dir=sdk, build_tools_dir=bt_dir, android_jar=android_jar,
                   javac=javac or "", java=java or "", zip=zip_exe or "", adb=adb,
                   keystore=keystore, keystore_pass=ks_pass, font=font,
                   config_path=config_path, warnings=tuple(warnings), **tools)
    return tc, r.rows, problems


def resolve(config_path=None, *, need_adb=False, env=None):
    """Resolve and validate the toolchain. Raises ConfigError listing every problem."""
    env = os.environ if env is None else env
    path = find_config(config_path, env)
    tc, _rows, problems = _resolve(path, env, need_adb)
    if problems:
        raise ConfigError(problems, path)
    return tc


def doctor_report(config_path=None, env=None):
    """Return (lines, ok) describing every resolved value, its origin and status."""
    env = os.environ if env is None else env
    try:
        path = find_config(config_path, env)
    except ConfigError as e:
        return [str(e)], False
    tc, rows, problems = _resolve(path, env, need_adb=False)
    lines = [f"config: {path or 'none (auto-detect)'}"]
    width = max(len(k) for k, _, _ in rows)
    for key, value, origin in rows:
        lines.append(f"  {key:<{width}}  {value or '-'}  [{origin}]")
    lines.append(f"  {'build tools':<{width}}  {tc.build_tools_dir}")
    lines += [f"warning: {w}" for w in tc.warnings]
    lines += [f"PROBLEM: {p}" for p in problems]
    lines.append("OK" if not problems else f"{len(problems)} problem(s)")
    return lines, not problems
