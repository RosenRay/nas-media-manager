from __future__ import annotations

from pathlib import Path
from typing import Any

from .media import (
    current_year,
    default_episode_title,
    default_media_date,
    inspect_batch_folder,
    is_video,
    resolve_media_path,
    sanitize_name,
    to_relative,
)
from .organizer import execute_plan, preview_plan, undo_operations


class BatchFolderError(RuntimeError):
    pass


def _direct_videos(folder: Path) -> list[Path]:
    try:
        videos = [child for child in folder.iterdir() if is_video(child)]
    except OSError as exc:
        raise BatchFolderError(f"无法读取目录：{to_relative(folder)}") from exc
    return sorted(videos, key=lambda p: (p.stat().st_mtime, p.name.casefold()))


def build_folder_collection_payload(folder_rel: str) -> dict[str, Any]:
    folder = resolve_media_path(folder_rel)
    if not folder.exists() or not folder.is_dir():
        raise BatchFolderError("选择项不是有效文件夹")
    info = inspect_batch_folder(folder)
    if not info["eligible"]:
        raise BatchFolderError(info["reason"] or "该文件夹不可批量处理")

    videos = _direct_videos(folder)
    if not videos:
        raise BatchFolderError("文件夹内没有可处理的视频")

    series_title = sanitize_name(folder.name, "未命名集合")
    output_parent = "" if folder.parent.resolve() == resolve_media_path("").resolve() else to_relative(folder.parent)
    episodes: list[dict[str, Any]] = []
    for idx, video in enumerate(videos, start=1):
        episodes.append({
            "source": to_relative(video),
            "episode": idx,
            "title": default_episode_title(video.name, idx),
            "plot": "",
            "aired": default_media_date(video),
            "duration": None,
            "duration_text": "—",
            "resolution": "—",
            "selected_thumb": "",
        })

    first_source = episodes[0]["source"]
    return {
        "source_dir": to_relative(folder),
        "mode": "organize",
        "organization_mode": "flat",
        "ugreen_compat": True,
        "auto_episode_thumbs": True,
        "series_title": series_title,
        "series_plot": "",
        "year": current_year(),
        "genres": "家庭影像",
        "season": 1,
        "season_title": "Season 01",
        "output_parent": output_parent,
        "poster_cache": "",
        "fanart_cache": "",
        "poster_source": first_source,
        "fanart_source": first_source,
        "selected_poster_thumb": "",
        "selected_fanart_thumb": "",
        "episodes": episodes,
    }


def build_batch_payload(selected_folder_rel_paths: list[str]) -> dict[str, Any]:
    if not selected_folder_rel_paths:
        raise BatchFolderError("请至少选择一个文件夹")

    items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in selected_folder_rel_paths:
        rel = str(raw or "").strip("/\\")
        if rel in seen:
            continue
        seen.add(rel)
        try:
            folder = resolve_media_path(rel)
            display_name = folder.name or rel or "/"
            payload = build_folder_collection_payload(rel)
            plan = preview_plan(payload, f"batch-check-{len(items)}")
            if plan["conflicts"]:
                skipped.append({
                    "folder": rel,
                    "name": display_name,
                    "reason": "存在冲突：" + "；".join(plan["conflicts"][:3]),
                })
                continue
            items.append({
                "folder": rel,
                "name": display_name,
                "series_title": payload["series_title"],
                "video_count": len(payload["episodes"]),
                "payload": payload,
            })
        except Exception as exc:
            try:
                name = resolve_media_path(rel).name or rel
            except Exception:
                name = rel or "未知目录"
            skipped.append({"folder": rel, "name": name, "reason": str(exc)})

    return {
        "kind": "batch_folders",
        "year": current_year(),
        "items": items,
        "skipped": skipped,
    }


def preview_batch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("kind") != "batch_folders":
        raise BatchFolderError("批量任务类型不正确")
    items: list[dict[str, Any]] = []
    for idx, item in enumerate(payload.get("items", [])):
        plan = preview_plan(item["payload"], f"batch-preview-{idx}")
        items.append({
            "folder": item["folder"],
            "name": item["name"],
            "series_title": item["series_title"],
            "video_count": item["video_count"],
            "target": plan["series_root"],
            "collection_dir": plan["collection_dir"],
            "conflicts": plan["conflicts"],
        })
    return {
        "items": items,
        "skipped": payload.get("skipped", []),
        "ready_count": sum(1 for item in items if not item["conflicts"]),
        "blocked_count": sum(1 for item in items if item["conflicts"]),
    }


def execute_batch_payload(payload: dict[str, Any], batch_id: str) -> list[dict[str, Any]]:
    if payload.get("kind") != "batch_folders":
        raise BatchFolderError("批量任务类型不正确")
    if not payload.get("items"):
        raise BatchFolderError("没有可执行的文件夹")

    operations: list[dict[str, Any]] = []
    try:
        for idx, item in enumerate(payload["items"]):
            operations.extend(execute_plan(item["payload"], f"{batch_id}-{idx}"))
        return operations
    except Exception as exc:
        rollback_errors = undo_operations(operations)
        if rollback_errors:
            raise BatchFolderError(f"批量执行失败：{exc}；回滚异常：{'；'.join(rollback_errors)}") from exc
        raise
