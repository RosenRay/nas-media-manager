from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

BOOTSTRAP_ROOT = Path(os.getenv("NMM_BOOTSTRAP_ROOT", "/opt/bootstrap")).resolve()
APP_RUNTIME_ROOT = Path(os.getenv("APP_RUNTIME_ROOT", "/data/app_runtime")).resolve()
VERSIONS_ROOT = APP_RUNTIME_ROOT / "versions"
CURRENT_LINK = APP_RUNTIME_ROOT / "current"
RESTART_FLAG = APP_RUNTIME_ROOT / "restart.flag"
HOST = os.getenv("NMM_HOST", "0.0.0.0")
PORT = os.getenv("NMM_PORT", "8000")

stopping = False
child: subprocess.Popen | None = None


def _read_version(root: Path) -> str:
    value = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"empty VERSION in {root}")
    return value


def _atomic_symlink(target: Path) -> None:
    APP_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    pending = APP_RUNTIME_ROOT / ".current-next"
    if pending.exists() or pending.is_symlink():
        pending.unlink()
    pending.symlink_to(target, target_is_directory=True)
    os.replace(pending, CURRENT_LINK)


def seed_bootstrap() -> None:
    VERSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    version = _read_version(BOOTSTRAP_ROOT)
    target = VERSIONS_ROOT / version
    if not target.exists():
        staging = VERSIONS_ROOT / f".{version}.bootstrap"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(BOOTSTRAP_ROOT, staging)
        os.replace(staging, target)

    if not CURRENT_LINK.is_symlink() or not CURRENT_LINK.exists():
        if CURRENT_LINK.exists() and not CURRENT_LINK.is_symlink():
            backup = APP_RUNTIME_ROOT / "legacy-current"
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(CURRENT_LINK, backup)
        _atomic_symlink(target)


def current_root() -> Path:
    if not CURRENT_LINK.is_symlink():
        raise RuntimeError("runtime current link is missing")
    root = CURRENT_LINK.resolve()
    if not (root / "app").is_dir() or not (root / "VERSION").is_file():
        raise RuntimeError(f"invalid application root: {root}")
    return root


def flag_mtime() -> int:
    try:
        return RESTART_FLAG.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def launch_child() -> subprocess.Popen:
    root = current_root()
    version = _read_version(root)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["NMM_RUNTIME_MANAGED"] = "1"
    env.setdefault("NMM_RUNTIME_API", "1")
    print(f"[runtime] starting NAS Media Manager v{version} from {root}", flush=True)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            PORT,
        ],
        cwd=root,
        env=env,
    )


def stop_child(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=12)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def handle_signal(signum, frame) -> None:  # noqa: ANN001
    global stopping
    stopping = True
    stop_child(child)


def main() -> int:
    global child
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    seed_bootstrap()
    observed_flag = flag_mtime()
    child = launch_child()

    while not stopping:
        time.sleep(1.0)
        now_flag = flag_mtime()
        if now_flag != observed_flag:
            observed_flag = now_flag
            print("[runtime] application switch detected, restarting uvicorn", flush=True)
            stop_child(child)
            if stopping:
                break
            child = launch_child()
            continue

        code = child.poll()
        if code is not None:
            if stopping:
                break
            print(f"[runtime] uvicorn exited with code {code}; restarting in 2s", flush=True)
            time.sleep(2.0)
            child = launch_child()

    stop_child(child)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
