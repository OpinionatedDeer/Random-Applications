"""Build (and optionally install and launch) many apps of one kind in parallel."""
import importlib
import os
import shutil
import signal
import sys
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass

from . import adb
from .adb import AdbError
from .apk import BuildError, build_apk
from .config import Toolchain


def kind_module(name):
    return importlib.import_module(f"apkgen.kinds.{name}")


@dataclass(frozen=True)
class Job:
    kind: str                 # module name under apkgen.kinds (imported in the worker)
    index: int
    opts: object
    tc: Toolchain
    prepared: object          # whatever the kind's prepare() returned
    out_dir: str
    run_root: str
    install: bool
    serial: str | None


@dataclass(frozen=True)
class Result:
    index: int
    package: str
    ok: bool
    step: str                 # "build" | "install" | "launch" | "internal"; "done" when ok
    message: str = ""
    launch: tuple[str, ...] | None = None


_interrupted = False  # set in a worker once Ctrl-C has been received


def _on_sigint(signum, frame):
    global _interrupted
    if _interrupted:
        return  # already unwinding; a second signal must not interrupt the cleanup
    _interrupted = True
    # Unwinds the current job (subprocess.run kills its child, finally removes the work dir).
    # concurrent.futures catches this and keeps the worker alive, so _work() skips any job
    # it is handed afterwards until the executor's shutdown sentinel arrives.
    raise SystemExit(130)


def _worker_init():
    # Keep an inherited SIG_IGN (e.g. `apkgen ... &` in a script), as the main process does.
    # A Python-level handler (not SIG_IGN) is reset on exec, so javac/d8/adb still receive
    # SIGINT from the terminal themselves; no traceback is printed per worker.
    if signal.getsignal(signal.SIGINT) != signal.SIG_IGN:
        signal.signal(signal.SIGINT, _on_sigint)


def _work(job):
    """Runs in a worker process. Never raises: every failure becomes a plain Result."""
    package = f"#{job.index}"
    if _interrupted:
        return Result(job.index, package, False, "interrupted")
    workdir = os.path.join(job.run_root, f"app{job.index}")
    step = "build"
    try:
        spec = kind_module(job.kind).make_spec(job.index, job.opts, job.tc, job.prepared)
        package = spec.package
        apk = build_apk(spec, job.tc, job.out_dir, workdir)
        if job.install:
            step = "install"
            adb.install(job.tc, apk, job.serial)
        return Result(job.index, package, True, "done", launch=spec.launch)
    except (BuildError, AdbError) as e:
        return Result(job.index, package, False, step, str(e))
    except Exception as e:
        return Result(job.index, package, False, "internal",
                      f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _report(res, install):
    if res.ok:
        print(f"Successfully built{' and installed' if install else ''} {res.package}", flush=True)
    elif res.step == "install":
        print(f"Built {res.package} but install failed: {res.message}", flush=True)
    else:
        print(f"Failed to build {res.package}: {res.message}", flush=True)


def _stop_workers(executor, grace=5.0):
    """After Ctrl-C or an unexpected error: give workers time to exit via their SIGINT handler
    (which also stops their child tools and removes their work dirs), terminate stragglers,
    and wait for all of them, so the scratch directory can be removed safely afterwards."""
    # Snapshot first: shutdown() drops the executor's reference to its processes.
    procs = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for proc in procs:  # covers SIGINT sent to the main process only (kill -INT <pid>)
        try:
            os.kill(proc.pid, signal.SIGINT)
        except (ProcessLookupError, TypeError):
            pass
    deadline = time.monotonic() + grace
    for proc in procs:
        proc.join(max(0.0, deadline - time.monotonic()))
    for proc in procs:
        if proc.is_alive():
            proc.terminate()
    for proc in procs:
        proc.join(5)


def run(kind_name, opts, tc, indices, out_dir, *, workers, install=False, launch=False, serial=None):
    """Build every index; returns the process exit code (0 ok, 1 failures, 130 interrupted)."""
    install = install or launch
    kind = kind_module(kind_name)
    try:
        os.makedirs(out_dir, exist_ok=True)
        # Scratch space lives inside out_dir so finished APKs can be moved into place atomically.
        run_root = tempfile.mkdtemp(prefix=f".apkgen-tmp-{os.getpid()}-", dir=out_dir)
    except OSError as e:
        print(f"apkgen: cannot use output directory {out_dir}: {e.strerror or e}", file=sys.stderr)
        return 2
    results = []
    executor = None
    try:
        prepare = getattr(kind, "prepare", None)
        prepared = prepare(tc, opts, os.path.join(run_root, "prepare")) if prepare else None
        jobs = [Job(kind_name, i, opts, tc, prepared, out_dir, run_root, install, serial) for i in indices]
        executor = ProcessPoolExecutor(max_workers=max(1, min(workers, len(jobs))), initializer=_worker_init)
        futures = {executor.submit(_work, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                res = future.result()
            except BrokenProcessPool as e:
                res = Result(job.index, f"#{job.index}", False, "internal", f"worker process died: {e}")
            except (SystemExit, KeyboardInterrupt):
                raise KeyboardInterrupt from None  # a worker was interrupted: stop the whole run
            except Exception as e:
                res = Result(job.index, f"#{job.index}", False, "internal", f"{type(e).__name__}: {e}")
            _report(res, install)
            results.append(res)
        executor.shutdown()

        if launch:
            # One at a time: concurrent `am start` calls can push each other aside.
            launch_errors = {}
            for res in sorted(results, key=lambda r: r.index):
                if not (res.ok and res.launch):
                    continue
                try:
                    adb.launch(tc, res.launch, serial)
                    print(f"Launched {res.package}", flush=True)
                except AdbError as e:
                    print(f"Failed to launch {res.package}: {e}", flush=True)
                    launch_errors[res.index] = str(e)
            results = [Result(r.index, r.package, False, "launch", launch_errors[r.index])
                       if r.index in launch_errors else r for r in results]
    except KeyboardInterrupt:
        if executor:
            _stop_workers(executor)
        print("interrupted", file=sys.stderr)
        return 130
    except BuildError as e:  # from prepare()
        print(f"Failed to prepare {kind_name} build: {e}", file=sys.stderr)
        return 1
    except BaseException:
        if executor:
            _stop_workers(executor)  # never leave workers running against a deleted run_root
        raise
    finally:
        shutil.rmtree(run_root, ignore_errors=True)

    failed = [r for r in results if not r.ok]
    counts = {}
    for r in failed:
        counts[r.step] = counts.get(r.step, 0) + 1
    detail = f" ({', '.join(f'{step} {n}' for step, n in sorted(counts.items()))})" if counts else ""
    print(f"{len(results) - len(failed)} ok, {len(failed)} failed{detail}")
    return 1 if failed else 0
