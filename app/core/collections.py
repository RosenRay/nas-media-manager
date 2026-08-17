from __future__ import annotations

import base64
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.config import MEDIA_ROOT
from .media import (
    default_episode_title,
    format_duration,
    is_video,
    probe_video,
    resolve_media_path,
    sanitize_name,
    to_relative,
)
from .nfo import episode_nfo, tvshow_nfo
from .thumbnails import extract_default_thumbnail

EPISODE_RE = re.compile(r"(?i)S(?P<season>\d{1,2})E(?P<episode>\d{1,3})")
SEASON_DIR_RE = re.compile(r"(?i)^Season[\s._-]*(\d+)$")


class CollectionError(RuntimeError):
    pass


class CollectionConflictError(CollectionError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_xml(path: Path) -> ET.Element | None:
    if not path.exists():
        return None
    try:
        return ET.parse(path).getroot()
    except Exception:
        return None


def _text(root: ET.Element | None, name: str, default: str = "") -> str:
    if root is None:
        return default
    node = root.find(name)
    return (node.text or "").strip() if node is not None and node.text else default


def _genres(root: ET.Element | None) -> list[str]:
    if root is None:
        return []
    return [(node.text or "").strip() for node in root.findall("genre") if (node.text or "").strip()]


def _episode_identity(path: Path) -> tuple[int, int] | None:
    match = EPISODE_RE.search(path.stem)
    if not match:
        return None
    return int(match.group("season")), int(match.group("episode"))


def _candidate_collection_root(video: Path) -> Path:
    if SEASON_DIR_RE.match(video.parent.name):
        return video.parent.parent
    return video.parent


def discover_collection_paths() -> list[Path]:
    roots: set[Path] = set()
    if not MEDIA_ROOT.exists():
        return []
    for nfo in MEDIA_ROOT.rglob("tvshow.nfo"):
        if nfo.is_file():
            roots.add(nfo.parent.resolve())
    # Detect UGREEN-compatible collections whose tvshow.nfo was accidentally
    # deleted without probing every media file in the whole NAS.
    for season_dir in MEDIA_ROOT.rglob("Season *"):
        if not season_dir.is_dir() or not SEASON_DIR_RE.match(season_dir.name):
            continue
        try:
            has_episode = any(is_video(child) and _episode_identity(child) for child in season_dir.iterdir())
        except OSError:
            has_episode = False
        if has_episode:
            roots.add(season_dir.parent.resolve())
    return sorted(roots, key=lambda p: to_relative(p).casefold())


def load_collection(relative: str, *, include_media_meta: bool = True) -> dict[str, Any]:
    root = resolve_media_path(relative)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError("集合目录不存在")

    tvshow_path = root / "tvshow.nfo"
    show_root = _parse_xml(tvshow_path)
    title = _text(show_root, "title", root.name)
    plot = _text(show_root, "plot")
    year = _text(show_root, "year")
    genres = _genres(show_root)

    videos: list[Path] = []
    for child in root.rglob("*"):
        if is_video(child) and _episode_identity(child):
            videos.append(child)
    videos.sort(key=lambda p: (_episode_identity(p) or (999, 999), p.name.casefold()))

    episodes: list[dict[str, Any]] = []
    duplicate_map: dict[tuple[int, int], list[str]] = {}
    for video in videos:
        identity = _episode_identity(video)
        if not identity:
            continue
        season, episode = identity
        duplicate_map.setdefault(identity, []).append(to_relative(video))
        nfo_path = video.with_suffix(".nfo")
        thumb_path = video.with_suffix(".jpg")
        ep_root = _parse_xml(nfo_path)
        meta = probe_video(video) if include_media_meta else {}
        episodes.append({
            "season": season,
            "episode": episode,
            "title": _text(ep_root, "title", default_episode_title(video.name, episode)),
            "plot": _text(ep_root, "plot"),
            "aired": _text(ep_root, "aired"),
            "showtitle": _text(ep_root, "showtitle", title),
            "video": to_relative(video),
            "filename": video.name,
            "nfo": to_relative(nfo_path),
            "thumb": to_relative(thumb_path),
            "nfo_exists": nfo_path.exists(),
            "nfo_valid": ep_root is not None,
            "thumb_exists": thumb_path.exists(),
            "duration_text": format_duration(meta.get("duration")),
            "resolution": f"{meta.get('width')}×{meta.get('height')}" if meta.get("width") and meta.get("height") else "—",
        })

    issues: list[dict[str, str]] = []
    if not tvshow_path.exists():
        issues.append({"code": "missing_tvshow", "message": "缺少 tvshow.nfo"})
    elif show_root is None:
        issues.append({"code": "invalid_tvshow", "message": "tvshow.nfo 无法解析"})
    if not (root / "poster.jpg").exists():
        issues.append({"code": "missing_poster", "message": "缺少 poster.jpg"})
    if not (root / "fanart.jpg").exists():
        issues.append({"code": "missing_fanart", "message": "缺少 fanart.jpg"})

    for ep in episodes:
        if not ep["nfo_exists"]:
            issues.append({"code": "missing_episode_nfo", "message": f"E{ep['episode']:02d} 缺少 NFO：{ep['filename']}"})
        elif not ep["nfo_valid"]:
            issues.append({"code": "invalid_episode_nfo", "message": f"E{ep['episode']:02d} NFO 无法解析：{Path(ep['nfo']).name}"})
        if not ep["thumb_exists"]:
            issues.append({"code": "missing_episode_thumb", "message": f"E{ep['episode']:02d} 缺少单集图片：{ep['filename']}"})

    for identity, paths in duplicate_map.items():
        if len(paths) > 1:
            issues.append({"code": "duplicate_episode", "message": f"S{identity[0]:02d}E{identity[1]:02d} 存在 {len(paths)} 个视频"})

    by_season: dict[int, list[int]] = {}
    for ep in episodes:
        by_season.setdefault(ep["season"], []).append(ep["episode"])
    for season, nums in by_season.items():
        unique = sorted(set(nums))
        if unique:
            missing = [i for i in range(unique[0], unique[-1] + 1) if i not in unique]
            if missing:
                issues.append({"code": "episode_gap", "message": f"Season {season:02d} 集数断号：" + ", ".join(f"E{x:02d}" for x in missing)})

    return {
        "path": to_relative(root),
        "name": root.name,
        "title": title,
        "plot": plot,
        "year": year,
        "genres": ", ".join(genres),
        "poster_exists": (root / "poster.jpg").exists(),
        "fanart_exists": (root / "fanart.jpg").exists(),
        "tvshow_exists": tvshow_path.exists(),
        "tvshow_valid": show_root is not None,
        "episodes": episodes,
        "episode_count": len(episodes),
        "issues": issues,
        "issue_count": len(issues),
        "max_episode": max((ep["episode"] for ep in episodes if ep["season"] == 1), default=0),
    }


def list_collections() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in discover_collection_paths():
        try:
            item = load_collection(to_relative(path), include_media_meta=False)
        except Exception:
            continue
        result.append(item)
    return result


def _write_with_backup(path: Path, content: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        before = path.read_bytes()
        path.write_text(content, encoding="utf-8")
        return {
            "type": "replace",
            "path": to_relative(path),
            "before_b64": base64.b64encode(before).decode("ascii"),
            "sha256": _sha256(path),
        }
    path.write_text(content, encoding="utf-8")
    return {"type": "write", "path": to_relative(path), "sha256": _sha256(path)}


def update_collection_metadata(relative: str, *, title: str, plot: str, year: str, genres: str) -> list[dict[str, Any]]:
    collection = load_collection(relative, include_media_meta=False)
    root = resolve_media_path(relative)
    clean_title = sanitize_name(title, collection["name"])
    genre_list = [x.strip() for x in genres.replace("，", ",").replace("/", ",").split(",") if x.strip()]
    operations: list[dict[str, Any]] = []
    try:
        operations.append(_write_with_backup(root / "tvshow.nfo", tvshow_nfo(title=clean_title, plot=plot.strip(), year=year.strip(), genres=genre_list)))
        # Keep existing episode NFO showtitle aligned with the collection title.
        for ep in collection["episodes"]:
            nfo_path = resolve_media_path(ep["nfo"])
            if not nfo_path.exists():
                continue
            operations.append(_write_with_backup(nfo_path, episode_nfo(
                title=ep["title"], showtitle=clean_title, season=ep["season"], episode=ep["episode"], plot=ep["plot"], aired=ep["aired"]
            )))
        return operations
    except Exception:
        from .organizer import undo_operations
        undo_operations(operations)
        raise


def update_episode_metadata(relative: str, video_rel: str, *, title: str, plot: str, aired: str) -> list[dict[str, Any]]:
    collection = load_collection(relative, include_media_meta=False)
    video = resolve_media_path(video_rel)
    root = resolve_media_path(relative)
    try:
        video.relative_to(root)
    except ValueError as exc:
        raise CollectionError("视频不属于该集合") from exc
    identity = _episode_identity(video)
    if not identity:
        raise CollectionError("无法从文件名识别 SxxExx")
    season, episode = identity
    content = episode_nfo(
        title=sanitize_name(title, f"第{episode}集"),
        showtitle=collection["title"],
        season=season,
        episode=episode,
        plot=plot.strip(),
        aired=aired.strip(),
    )
    return [_write_with_backup(video.with_suffix(".nfo"), content)]


def repair_collection(relative: str, *, repair_tvshow: bool, repair_episode_nfo: bool, repair_episode_thumbs: bool) -> list[dict[str, Any]]:
    collection = load_collection(relative, include_media_meta=False)
    root = resolve_media_path(relative)
    operations: list[dict[str, Any]] = []
    try:
        if repair_tvshow and (not (root / "tvshow.nfo").exists() or not collection.get("tvshow_valid")):
            operations.append(_write_with_backup(root / "tvshow.nfo", tvshow_nfo(
                title=collection["title"], plot=collection["plot"], year=collection["year"],
                genres=[x.strip() for x in collection["genres"].split(",") if x.strip()],
            )))
        for ep in collection["episodes"]:
            video = resolve_media_path(ep["video"])
            nfo_path = video.with_suffix(".nfo")
            thumb_path = video.with_suffix(".jpg")
            if repair_episode_nfo and not ep.get("nfo_valid"):
                operations.append(_write_with_backup(nfo_path, episode_nfo(
                    title=ep["title"], showtitle=collection["title"], season=ep["season"], episode=ep["episode"], plot=ep["plot"], aired=ep["aired"]
                )))
            if repair_episode_thumbs and not thumb_path.exists():
                extract_default_thumbnail(video, thumb_path)
                operations.append({"type": "write", "path": to_relative(thumb_path), "sha256": _sha256(thumb_path)})
        return operations
    except Exception:
        # Caller records the error. Newly created files can be removed by task undo;
        # for this synchronous repair path, best effort cleanup of this run is safer.
        from .organizer import undo_operations
        undo_operations(operations)
        raise


def build_append_payload(collection_rel: str, selected_rel_paths: list[str]) -> dict[str, Any]:
    collection = load_collection(collection_rel, include_media_meta=False)
    root = resolve_media_path(collection_rel)
    selected = [resolve_media_path(p) for p in selected_rel_paths]
    if not selected:
        raise CollectionError("至少选择一个新增视频")
    if any(not is_video(p) for p in selected):
        raise CollectionError("选择项中包含非视频文件")
    for path in selected:
        try:
            path.relative_to(root)
            raise CollectionError("不能把集合内部已有视频再次追加到同一个集合")
        except ValueError:
            pass
    selected.sort(key=lambda p: (p.stat().st_mtime, p.name.casefold()))
    start = collection["max_episode"] + 1
    episodes: list[dict[str, Any]] = []
    for offset, path in enumerate(selected):
        episode_no = start + offset
        meta = probe_video(path)
        episodes.append({
            "source": to_relative(path),
            "episode": episode_no,
            "title": default_episode_title(path.name, episode_no),
            "plot": "",
            "aired": "",
            "duration_text": format_duration(meta.get("duration")),
            "resolution": f"{meta.get('width')}×{meta.get('height')}" if meta.get("width") and meta.get("height") else "—",
        })
    return {
        "kind": "append",
        "collection_path": collection["path"],
        "series_title": collection["title"],
        "auto_episode_thumbs": True,
        "episodes": episodes,
    }


def apply_append_form(payload: dict[str, Any], form: Any) -> None:
    payload["auto_episode_thumbs"] = str(form.get("auto_episode_thumbs", "0")) == "1"
    for idx, ep in enumerate(payload.get("episodes", [])):
        ep["title"] = str(form.get(f"title_{idx}", ep.get("title", ""))).strip()
        ep["plot"] = str(form.get(f"plot_{idx}", ep.get("plot", ""))).strip()
        ep["aired"] = str(form.get(f"aired_{idx}", ep.get("aired", ""))).strip()


def _stable_filename_prefix(collection: dict[str, Any]) -> str:
    # Keep the filename prefix already used by the collection even if the user
    # later edits the display title in tvshow.nfo. This avoids mixing two title
    # prefixes inside one UGREEN-scanned collection.
    for ep in collection.get("episodes", []):
        stem = Path(ep.get("filename", "")).stem
        match = EPISODE_RE.search(stem)
        if match:
            prefix = stem[:match.start()].rstrip(" ._-")
            if prefix:
                return prefix
    return sanitize_name(collection.get("name", ""), "集合")


def preview_append(payload: dict[str, Any]) -> dict[str, Any]:
    collection = load_collection(payload["collection_path"], include_media_meta=False)
    root = resolve_media_path(collection["path"])
    season_dir = root / "Season 01"
    filename_prefix = _stable_filename_prefix(collection)
    items: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for ep in payload.get("episodes", []):
        source = resolve_media_path(ep["source"])
        episode_no = int(ep["episode"])
        base = f"{filename_prefix} - S01E{episode_no:02d}"
        target_video = season_dir / f"{base}{source.suffix.lower()}"
        target_nfo = season_dir / f"{base}.nfo"
        target_thumb = season_dir / f"{base}.jpg"
        for target in (target_video, target_nfo):
            if target.exists():
                conflicts.append(f"目标已存在：{to_relative(target)}")
        if payload.get("auto_episode_thumbs") and target_thumb.exists():
            conflicts.append(f"目标已存在：{to_relative(target_thumb)}")
        items.append({
            "source": to_relative(source),
            "target": to_relative(target_video),
            "nfo": to_relative(target_nfo),
            "thumb": to_relative(target_thumb),
            "episode": episode_no,
            "title": sanitize_name(ep.get("title", ""), f"第{episode_no}集"),
            "plot": ep.get("plot", ""),
            "aired": ep.get("aired", ""),
        })
    return {
        "collection": collection,
        "items": items,
        "conflicts": conflicts,
        "auto_episode_thumbs": bool(payload.get("auto_episode_thumbs")),
    }


def execute_append(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plan = preview_append(payload)
    if plan["conflicts"]:
        raise CollectionConflictError("；".join(plan["conflicts"]))
    collection = plan["collection"]
    root = resolve_media_path(collection["path"])
    season_dir = root / "Season 01"
    operations: list[dict[str, Any]] = []
    try:
        if not season_dir.exists():
            season_dir.mkdir(parents=True, exist_ok=False)
            operations.append({"type": "mkdir", "path": to_relative(season_dir)})
        for item in plan["items"]:
            source = resolve_media_path(item["source"])
            target = resolve_media_path(item["target"])
            shutil.move(str(source), str(target))
            operations.append({"type": "move", "src": item["source"], "dst": item["target"]})
            nfo_path = resolve_media_path(item["nfo"])
            nfo_path.write_text(episode_nfo(
                title=item["title"], showtitle=collection["title"], season=1, episode=item["episode"], plot=item["plot"], aired=item["aired"]
            ), encoding="utf-8")
            operations.append({"type": "write", "path": item["nfo"], "sha256": _sha256(nfo_path)})
            if plan["auto_episode_thumbs"]:
                thumb_path = resolve_media_path(item["thumb"])
                extract_default_thumbnail(target, thumb_path)
                operations.append({"type": "write", "path": item["thumb"], "sha256": _sha256(thumb_path)})
        return operations
    except Exception:
        from .organizer import undo_operations
        undo_operations(operations)
        raise
