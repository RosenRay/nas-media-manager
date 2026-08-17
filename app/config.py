from __future__ import annotations

import os
from pathlib import Path

MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/media")).expanduser().resolve()
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data")).expanduser().resolve()
DB_PATH = DATA_ROOT / "media_manager.db"
UPLOAD_ROOT = DATA_ROOT / "uploads"
THUMB_ROOT = DATA_ROOT / "thumbs"
APP_RUNTIME_ROOT = Path(os.getenv("APP_RUNTIME_ROOT", str(DATA_ROOT / "app_runtime"))).expanduser().resolve()
UPDATE_REPOSITORY = os.getenv("UPDATE_REPOSITORY", "RosenRay/nas-media-manager").strip() or "RosenRay/nas-media-manager"

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".m4v", ".ts", ".mts", ".m2ts",
    ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".3gp"
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def ensure_runtime_dirs() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    THUMB_ROOT.mkdir(parents=True, exist_ok=True)
    APP_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
