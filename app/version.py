from __future__ import annotations

from pathlib import Path


def app_package_root() -> Path:
    """Return the directory that contains VERSION and app/."""
    return Path(__file__).resolve().parents[1]


def get_app_version() -> str:
    version_file = app_package_root() / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"
    return value or "dev"


APP_VERSION = get_app_version()
