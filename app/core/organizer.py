from __future__ import annotations

import base64
import hashlib
import shutil
from pathlib import Path
from typing import Any

from .media import resolve_media_path, sanitize_name, to_relative
from .nfo import episode_nfo, season_nfo, tvshow_nfo
from .thumbnails import (
    artwork_cache_path,
    extract_default_thumbnail,
    thumb_cache_path,
    upload_cache_path,
)


class PlanConflictError(RuntimeError):
    pass


# "家庭影像 / 不分季" is a user-facing concept. In UGREEN compatibility
# mode we still emit episodes inside Season 01 and retain season=1 in NFO so
# the NAS movie app can group episodes using its TV-style scanner.
FLAT_COLLECTION_SEASON = 1
UGREEN_FLAT_USE_SEASON_DIR = True
UGREEN_FLAT_WRITE_SEASON_NFO = False
UGREEN_FLAT_FILENAME_INCLUDE_TITLE = False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _genres(raw: str) -> list[str]:
    normalized = raw.replace("，", ",").replace("/", ",").replace("|", ",")
    return [x.strip() for x in normalized.split(",") if x.strip()]


def _artwork_source(payload: dict[str, Any], draft_id: str, kind: str) -> Path | None:
    selected = str(payload.get(f"selected_{kind}_thumb") or "").strip()
    if selected:
        return artwork_cache_path(draft_id, kind, Path(selected).name)
    uploaded = str(payload.get(f"{kind}_cache") or "").strip()
    if uploaded:
        return upload_cache_path(draft_id, Path(uploaded).name)
    return None


def build_plan(payload: dict[str, Any], draft_id: str) -> dict[str, Any]:
    series = sanitize_name(payload.get("series_title", ""), "未命名集合")
    mode = payload.get("mode", "organize")
    if mode not in {"organize", "metadata_only"}:
        mode = "organize"

    organization_mode = payload.get("organization_mode", "flat")
    if organization_mode not in {"flat", "seasoned"}:
        organization_mode = "flat"

    # New drafts default to UGREEN-compatible output. Old v0.1.2 drafts do not
    # contain this field, so they preserve their previous flat-root behaviour.
    ugreen_compat = bool(payload.get("ugreen_compat", False))
    auto_episode_thumbs = bool(payload.get("auto_episode_thumbs", False))

    season = int(payload.get("season") or 1)
    if organization_mode == "flat":
        season = FLAT_COLLECTION_SEASON

    output_parent = str(payload.get("output_parent", "")).strip("/\\")
    parent_abs = resolve_media_path(output_parent)
    series_root = parent_abs / series
    default_season_dir = series_root / f"Season {season:02d}"

    # User-facing no-season collections can still use a Season 01 directory on
    # disk solely for UGREEN grouping compatibility.
    flat_uses_season_dir = organization_mode == "flat" and ugreen_compat and UGREEN_FLAT_USE_SEASON_DIR
    collection_dir = default_season_dir if (organization_mode == "seasoned" or flat_uses_season_dir) else series_root

    episode_sources = [resolve_media_path(ep["source"]) for ep in payload.get("episodes", [])]
    common_source_parent = None
    if episode_sources and all(p.parent == episode_sources[0].parent for p in episode_sources):
        common_source_parent = episode_sources[0].parent

    metadata_episode_dir = common_source_parent if mode == "metadata_only" and common_source_parent else collection_dir

    moves: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    conflicts: list[str] = []

    tvshow_path = series_root / "tvshow.nfo"
    generated.append({
        "kind": "text",
        "path": tvshow_path,
        "content": tvshow_nfo(
            title=series,
            plot=payload.get("series_plot", ""),
            year=str(payload.get("year", "") or ""),
            genres=_genres(payload.get("genres", "")),
        ),
    })

    should_write_season_nfo = organization_mode == "seasoned"
    if organization_mode == "flat" and ugreen_compat:
        should_write_season_nfo = UGREEN_FLAT_WRITE_SEASON_NFO
    if should_write_season_nfo:
        season_path = metadata_episode_dir / "season.nfo"
        generated.append({
            "kind": "text",
            "path": season_path,
            "content": season_nfo(season=season, title=payload.get("season_title") or f"Season {season:02d}"),
        })

    for kind in ("poster", "fanart"):
        source = _artwork_source(payload, draft_id, kind)
        if source:
            generated.append({"kind": "copy", "path": series_root / f"{kind}.jpg", "source": source})

    seen_targets: set[Path] = set()
    for ep_index, ep in enumerate(payload.get("episodes", [])):
        source = resolve_media_path(ep["source"])
        episode_no = int(ep.get("episode") or 1)
        title = sanitize_name(ep.get("title", ""), f"第{episode_no}集")

        if mode == "metadata_only":
            target_video = source
            target_nfo = source.with_suffix(".nfo")
            target_thumb = source.with_suffix(".jpg")
        else:
            if organization_mode == "flat" and ugreen_compat and not UGREEN_FLAT_FILENAME_INCLUDE_TITLE:
                # Keep the media filename scraper-friendly. Human-readable titles
                # remain in the episode NFO instead of becoming a second title cue.
                base = f"{series} - S{season:02d}E{episode_no:02d}"
            elif organization_mode == "flat":
                base = f"{series} - S{season:02d}E{episode_no:02d} - {title}"
            else:
                base = f"{series} - S{season:02d}E{episode_no:02d} - {title}"
            target_video = collection_dir / f"{base}{source.suffix.lower()}"
            target_nfo = collection_dir / f"{base}.nfo"
            target_thumb = collection_dir / f"{base}.jpg"
            if target_video in seen_targets:
                conflicts.append(f"存在重复目标文件：{to_relative(target_video)}")
            seen_targets.add(target_video)
            moves.append({"source": source, "target": target_video, "episode": episode_no, "title": title})

        generated.append({
            "kind": "text",
            "path": target_nfo,
            "content": episode_nfo(
                title=title,
                showtitle=series,
                season=season,
                episode=episode_no,
                plot=ep.get("plot", ""),
                aired=ep.get("aired", ""),
            ),
        })

        selected_thumb = ep.get("selected_thumb") or ""
        if selected_thumb:
            generated.append({
                "kind": "copy",
                "path": target_thumb,
                "source": thumb_cache_path(draft_id, ep_index, Path(selected_thumb).name),
            })
        elif auto_episode_thumbs:
            # For organize mode the move happens before media generation, so the
            # automatic frame source is the final video path. metadata_only keeps
            # the source in place and uses it directly.
            generated.append({
                "kind": "auto_thumb",
                "path": target_thumb,
                "source_video": target_video,
            })

    for source in episode_sources:
        if not source.exists():
            conflicts.append(f"源文件不存在：{to_relative(source)}")

    for move in moves:
        src = move["source"]
        dst = move["target"]
        if dst.exists() and dst.resolve() != src.resolve():
            conflicts.append(f"目标视频已存在：{to_relative(dst)}")
    for item in generated:
        if item["path"].exists():
            conflicts.append(f"将生成的文件已存在：{to_relative(item['path'])}")
        if item["kind"] == "copy" and not item["source"].exists():
            conflicts.append(f"缓存图片不存在：{item['source'].name}")

    return {
        "mode": mode,
        "organization_mode": organization_mode,
        "ugreen_compat": ugreen_compat,
        "flat_uses_season_dir": flat_uses_season_dir,
        "auto_episode_thumbs": auto_episode_thumbs,
        "series": series,
        "season": season,
        "series_root": series_root,
        "collection_dir": collection_dir,
        "season_dir": metadata_episode_dir,
        "moves": moves,
        "generated": generated,
        "conflicts": conflicts,
    }


def preview_plan(payload: dict[str, Any], draft_id: str) -> dict[str, Any]:
    plan = build_plan(payload, draft_id)
    return {
        "mode": plan["mode"],
        "organization_mode": plan["organization_mode"],
        "ugreen_compat": plan["ugreen_compat"],
        "flat_uses_season_dir": plan["flat_uses_season_dir"],
        "auto_episode_thumbs": plan["auto_episode_thumbs"],
        "series": plan["series"],
        "season": plan["season"],
        "series_root": to_relative(plan["series_root"]),
        "season_dir": to_relative(plan["season_dir"]),
        "collection_dir": to_relative(plan["collection_dir"]),
        "moves": [
            {"source": to_relative(x["source"]), "target": to_relative(x["target"]), "episode": x["episode"], "title": x["title"]}
            for x in plan["moves"]
        ],
        "generated": [
            {
                "kind": x["kind"],
                "path": to_relative(x["path"]),
                "source": x.get("source", "").name if x.get("source") else "",
            }
            for x in plan["generated"]
        ],
        "conflicts": plan["conflicts"],
    }


def _rollback(operations: list[dict[str, Any]]) -> None:
    for op in reversed(operations):
        try:
            if op["type"] in {"write", "copy"}:
                path = resolve_media_path(op["path"])
                if path.exists():
                    path.unlink()
            elif op["type"] == "replace":
                path = resolve_media_path(op["path"])
                if path.exists():
                    path.write_bytes(base64.b64decode(op.get("before_b64", "")))
            elif op["type"] == "move":
                src = resolve_media_path(op["src"])
                dst = resolve_media_path(op["dst"])
                if dst.exists() and not src.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
            elif op["type"] == "mkdir":
                path = resolve_media_path(op["path"])
                if path.exists() and path.is_dir():
                    path.rmdir()
        except Exception:
            pass


def execute_plan(payload: dict[str, Any], draft_id: str) -> list[dict[str, Any]]:
    plan = build_plan(payload, draft_id)
    if plan["conflicts"]:
        raise PlanConflictError("；".join(plan["conflicts"]))

    operations: list[dict[str, Any]] = []
    try:
        directories = [plan["series_root"]]
        if plan["mode"] == "organize" and plan["collection_dir"] != plan["series_root"]:
            directories.append(plan["collection_dir"])
        for directory in directories:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=False)
                operations.append({"type": "mkdir", "path": to_relative(directory)})

        for move in plan["moves"]:
            src, dst = move["source"], move["target"]
            if src.resolve() == dst.resolve():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            operations.append({"type": "move", "src": to_relative(src), "dst": to_relative(dst)})

        for item in plan["generated"]:
            target: Path = item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if item["kind"] == "text":
                target.write_text(item["content"], encoding="utf-8")
                operations.append({"type": "write", "path": to_relative(target), "sha256": _sha256(target)})
            elif item["kind"] == "copy":
                shutil.copy2(item["source"], target)
                operations.append({"type": "copy", "path": to_relative(target), "sha256": _sha256(target)})
            elif item["kind"] == "auto_thumb":
                extract_default_thumbnail(item["source_video"], target)
                operations.append({"type": "write", "path": to_relative(target), "sha256": _sha256(target)})
        return operations
    except Exception:
        _rollback(operations)
        raise


def undo_operations(operations: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for op in reversed(operations):
        try:
            if op["type"] in {"write", "copy"}:
                path = resolve_media_path(op["path"])
                if path.exists():
                    expected = op.get("sha256")
                    if expected and _sha256(path) != expected:
                        raise RuntimeError(f"文件已被修改，拒绝删除：{op['path']}")
                    path.unlink()
            elif op["type"] == "replace":
                path = resolve_media_path(op["path"])
                if not path.exists():
                    raise RuntimeError(f"已修改文件不存在，无法撤销：{op['path']}")
                expected = op.get("sha256")
                if expected and _sha256(path) != expected:
                    raise RuntimeError(f"文件已再次修改，拒绝覆盖：{op['path']}")
                path.write_bytes(base64.b64decode(op.get("before_b64", "")))
            elif op["type"] == "move":
                src = resolve_media_path(op["src"])
                dst = resolve_media_path(op["dst"])
                if src.exists():
                    raise RuntimeError(f"原位置已有文件，无法撤销：{op['src']}")
                if not dst.exists():
                    raise RuntimeError(f"整理后的文件不存在：{op['dst']}")
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
            elif op["type"] == "mkdir":
                path = resolve_media_path(op["path"])
                if path.exists() and path.is_dir():
                    try:
                        path.rmdir()
                    except OSError:
                        pass
        except Exception as exc:
            errors.append(str(exc))
    return errors
