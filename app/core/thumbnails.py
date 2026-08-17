from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import THUMB_ROOT, UPLOAD_ROOT
from .media import probe_video, resolve_media_path


def _extract_candidates(source_rel: str, target_dir: Path, count: int = 5) -> list[Path]:
    source = resolve_media_path(source_rel)
    meta = probe_video(source)
    duration = float(meta.get("duration") or 0)
    if duration <= 0:
        raise ValueError("无法读取视频时长，不能生成候选缩略图")

    target_dir.mkdir(parents=True, exist_ok=True)
    for old in target_dir.glob("candidate_*.jpg"):
        old.unlink(missing_ok=True)

    ratios = [0.10, 0.30, 0.50, 0.70, 0.90]
    if count != 5:
        ratios = [(i + 1) / (count + 1) for i in range(count)]

    outputs: list[Path] = []
    for idx, ratio in enumerate(ratios, start=1):
        at = max(0.1, min(duration - 0.1, duration * ratio))
        out = target_dir / f"candidate_{idx:02d}.jpg"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{at:.3f}", "-i", str(source),
                "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(out),
            ],
            check=True,
            timeout=30,
        )
        outputs.append(out)
    return outputs


def generate_candidates(draft_id: str, episode_index: int, source_rel: str, count: int = 5) -> list[Path]:
    return _extract_candidates(source_rel, THUMB_ROOT / draft_id / "episodes" / str(episode_index), count)


def generate_artwork_candidates(draft_id: str, kind: str, source_rel: str, count: int = 5) -> list[Path]:
    if kind not in {"poster", "fanart"}:
        raise ValueError("不支持的图片类型")
    return _extract_candidates(source_rel, THUMB_ROOT / draft_id / "artwork" / kind, count)


def save_uploaded_artwork(draft_id: str, kind: str, filename: str, content: bytes) -> str:
    if kind not in {"poster", "fanart"}:
        raise ValueError("不支持的图片类型")
    target_dir = UPLOAD_ROOT / draft_id
    target_dir.mkdir(parents=True, exist_ok=True)
    temp = target_dir / f".{kind}_upload{Path(filename or '').suffix.lower() or '.img'}"
    temp.write_bytes(content)
    output = target_dir / f"{kind}.jpg"
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(temp), "-frames:v", "1", "-q:v", "2", str(output)],
            check=True,
            timeout=20,
        )
    finally:
        temp.unlink(missing_ok=True)
    return str(output)


def _safe_cache_path(base: Path, filename: str) -> Path:
    base = base.resolve()
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("非法缓存图片路径") from exc
    return candidate


def thumb_cache_path(draft_id: str, episode_index: int, filename: str) -> Path:
    return _safe_cache_path(THUMB_ROOT / draft_id / "episodes" / str(episode_index), filename)


def artwork_cache_path(draft_id: str, kind: str, filename: str) -> Path:
    if kind not in {"poster", "fanart"}:
        raise ValueError("不支持的图片类型")
    return _safe_cache_path(THUMB_ROOT / draft_id / "artwork" / kind, filename)


def upload_cache_path(draft_id: str, filename: str) -> Path:
    return _safe_cache_path(UPLOAD_ROOT / draft_id, filename)


def extract_default_thumbnail(source: Path, target: Path, ratio: float = 0.5) -> Path:
    """Extract one representative frame directly to the final artwork path."""
    meta = probe_video(source)
    duration = float(meta.get("duration") or 0)
    if duration <= 0:
        raise ValueError(f"无法读取视频时长，不能自动生成单集封面：{source.name}")
    at = max(0.1, min(duration - 0.1, duration * ratio))
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{at:.3f}", "-i", str(source),
            "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(target),
        ],
        check=True,
        timeout=30,
    )
    return target
