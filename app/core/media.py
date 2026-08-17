from __future__ import annotations

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import MEDIA_ROOT, VIDEO_EXTENSIONS


class MediaPathError(ValueError):
    pass


def media_root() -> Path:
    return MEDIA_ROOT


def resolve_media_path(relative: str | Path = "") -> Path:
    rel = str(relative or "").lstrip("/\\")
    candidate = (MEDIA_ROOT / rel).resolve()
    try:
        candidate.relative_to(MEDIA_ROOT)
    except ValueError as exc:
        raise MediaPathError("路径超出了已授权的媒体目录") from exc
    return candidate


def to_relative(path: Path) -> str:
    return path.resolve().relative_to(MEDIA_ROOT).as_posix()


def is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def current_year() -> str:
    return str(datetime.now().year)


def default_media_date(path: Path) -> str:
    """Return a stable default date for episode metadata.

    Some copied/exported files carry an invalid Unix-epoch mtime (1970). For
    those values we use today's date instead of writing 1970 into the NFO.
    """
    now = datetime.now()
    try:
        value = datetime.fromtimestamp(path.stat().st_mtime)
    except (OSError, OverflowError, ValueError):
        value = now
    if value.year < 1980 or value.year > now.year + 1:
        value = now
    return value.strftime("%Y-%m-%d")


def inspect_batch_folder(path: Path) -> dict[str, Any]:
    """Inspect one folder for the shallow one-folder-one-collection workflow.

    Batch mode intentionally considers only videos directly inside the selected
    folder. Nested folders are left untouched so selecting a high-level folder
    cannot accidentally merge several child collections together.
    """
    result = {"video_count": 0, "eligible": False, "reason": ""}
    if not path.exists() or not path.is_dir():
        result["reason"] = "目录不存在"
        return result
    if (path / "tvshow.nfo").exists():
        result["reason"] = "已整理集合"
        return result
    try:
        children = list(path.iterdir())
    except OSError:
        result["reason"] = "无法读取目录"
        return result

    # A Season xx folder containing scraper-style SxxExx videos is treated as
    # an existing/incomplete managed collection even if tvshow.nfo is missing.
    episode_re = re.compile(r"(?i)S\d{1,2}E\d{1,3}")
    for child in children:
        if child.is_dir() and re.match(r"(?i)^Season[\s._-]*\d+$", child.name):
            try:
                if any(is_video(item) and episode_re.search(item.stem) for item in child.iterdir()):
                    result["reason"] = "疑似已整理集合"
                    return result
            except OSError:
                pass

    videos = [child for child in children if is_video(child)]
    result["video_count"] = len(videos)
    if not videos:
        result["reason"] = "无视频"
        return result
    result["eligible"] = True
    return result


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def probe_video(path: Path, timeout: int = 8) -> dict[str, Any]:
    result: dict[str, Any] = {"duration": None, "width": None, "height": None, "codec": None}
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_name,width,height,codec_type",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        data = json.loads(proc.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        if duration is not None:
            result["duration"] = float(duration)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                result["width"] = stream.get("width")
                result["height"] = stream.get("height")
                result["codec"] = stream.get("codec_name")
                break
    except Exception:
        pass
    return result


def scan_directory(relative: str = "") -> dict[str, Any]:
    current = resolve_media_path(relative)
    if not current.exists() or not current.is_dir():
        raise FileNotFoundError("目录不存在")

    entries: list[dict[str, Any]] = []
    videos: list[tuple[int, Path]] = []
    for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
        try:
            stat = child.stat()
        except OSError:
            continue
        item = {
            "name": child.name,
            "rel_path": to_relative(child),
            "is_dir": child.is_dir(),
            "is_video": is_video(child),
            "size": stat.st_size if child.is_file() else None,
            "size_text": human_size(stat.st_size) if child.is_file() else "—",
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "duration": None,
            "duration_text": "—",
            "resolution": "—",
            "codec": "—",
        }
        if item["is_dir"]:
            batch = inspect_batch_folder(child)
            item["batch_video_count"] = batch["video_count"]
            item["batch_eligible"] = batch["eligible"]
            item["batch_skip_reason"] = batch["reason"]
        else:
            item["batch_video_count"] = 0
            item["batch_eligible"] = False
            item["batch_skip_reason"] = ""

        idx = len(entries)
        entries.append(item)
        if item["is_video"]:
            videos.append((idx, child))

    # Avoid opening too many videos simultaneously on low-power NAS devices.
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(videos)))) as pool:
        futures = {pool.submit(probe_video, path): idx for idx, path in videos}
        for future in as_completed(futures):
            idx = futures[future]
            meta = future.result()
            entries[idx]["duration"] = meta["duration"]
            entries[idx]["duration_text"] = format_duration(meta["duration"])
            if meta["width"] and meta["height"]:
                entries[idx]["resolution"] = f"{meta['width']}×{meta['height']}"
            entries[idx]["codec"] = meta["codec"] or "—"

    parent = ""
    if current != MEDIA_ROOT:
        parent = to_relative(current.parent)
    return {
        "current": to_relative(current),
        "parent": parent,
        "entries": entries,
    }


def clean_episode_title(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^[\s._-]*\d{1,4}[\s._-]+", "", stem)
    stem = re.sub(r"(?i)^s\d{1,2}e\d{1,3}[\s._-]*", "", stem)
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip(" ._-")
    return stem or Path(filename).stem


def default_episode_title(filename: str, episode_no: int) -> str:
    """Return a human-friendly default title.

    Phone/app exports often use opaque 32+ hex IDs. Keeping those IDs in both
    the filename and NFO can make a TV-style scraper treat episodes as unrelated
    titles. For such names we deliberately fall back to a stable human label.
    """
    title = clean_episode_title(filename)
    compact = re.sub(r"[\s._-]+", "", title)
    if re.fullmatch(r"(?i)[0-9a-f]{24,64}", compact):
        return f"第{episode_no}集"
    return title or f"第{episode_no}集"


def sanitize_name(value: str, fallback: str = "未命名") -> str:
    value = value.strip()
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


def default_draft(selected_rel_paths: list[str]) -> dict[str, Any]:
    selected = [resolve_media_path(p) for p in selected_rel_paths]
    if not selected:
        raise ValueError("至少选择一个视频")
    if any(not is_video(p) for p in selected):
        raise ValueError("选择项中包含非视频文件")

    selected = sorted(selected, key=lambda p: (p.stat().st_mtime, p.name.casefold()))
    common_parent = Path(os.path.commonpath([str(p.parent) for p in selected]))
    try:
        common_rel = to_relative(common_parent)
    except ValueError:
        common_parent = MEDIA_ROOT
        common_rel = ""

    detected_season = 1
    season_match = re.match(r"(?i)^season[\s._-]*(\d+)$", common_parent.name)
    if season_match and common_parent.parent != MEDIA_ROOT:
        detected_season = max(1, int(season_match.group(1)))
        series_title = common_parent.parent.name
        output_parent = to_relative(common_parent.parent.parent)
    else:
        series_title = common_parent.name if common_parent != MEDIA_ROOT else "新建剧集"
        output_parent = to_relative(common_parent.parent) if common_parent != MEDIA_ROOT else ""

    episodes = []
    for idx, path in enumerate(selected, start=1):
        meta = probe_video(path)
        episodes.append({
            "source": to_relative(path),
            "episode": idx,
            "title": default_episode_title(path.name, idx),
            "plot": "",
            "aired": default_media_date(path),
            "duration": meta.get("duration"),
            "duration_text": format_duration(meta.get("duration")),
            "resolution": f"{meta.get('width')}×{meta.get('height')}" if meta.get("width") and meta.get("height") else "—",
            "selected_thumb": "",
        })

    return {
        "source_dir": common_rel,
        "mode": "organize",
        "organization_mode": "flat",
        "ugreen_compat": True,
        "auto_episode_thumbs": True,
        "series_title": series_title,
        "series_plot": "",
        "year": current_year(),
        "genres": "家庭影像",
        "season": detected_season,
        "season_title": f"Season {detected_season:02d}",
        "output_parent": output_parent,
        "poster_cache": "",
        "fanart_cache": "",
        "poster_source": episodes[0]["source"] if episodes else "",
        "fanart_source": episodes[0]["source"] if episodes else "",
        "selected_poster_thumb": "",
        "selected_fanart_thumb": "",
        "episodes": episodes,
    }
