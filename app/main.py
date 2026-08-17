from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from app.config import MEDIA_ROOT, THUMB_ROOT, UPLOAD_ROOT, ensure_runtime_dirs
from app.core.media import MediaPathError, default_draft, scan_directory
from app.core.collections import (
    CollectionConflictError,
    CollectionError,
    apply_append_form,
    build_append_payload,
    execute_append,
    list_collections,
    load_collection,
    preview_append,
    repair_collection,
    update_collection_metadata,
    update_episode_metadata,
)
from app.core.organizer import PlanConflictError, execute_plan, preview_plan, undo_operations
from app.core.thumbnails import generate_artwork_candidates, generate_candidates, save_uploaded_artwork
from app.db import (
    create_task,
    get_draft,
    get_task,
    init_db,
    list_drafts,
    list_tasks,
    save_draft,
    update_task,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_dirs()
    init_db()
    yield


ensure_runtime_dirs()
app = FastAPI(title="NAS Media Manager", version="0.1.4", lifespan=lifespan)
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/thumb-cache", StaticFiles(directory=THUMB_ROOT), name="thumb-cache")
app.mount("/upload-cache", StaticFiles(directory=UPLOAD_ROOT), name="upload-cache")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["urlquote"] = lambda v: quote(str(v), safe="")


def render(request: Request, template: str, **context):
    base = {
        "request": request,
        "media_root": str(MEDIA_ROOT),
    }
    base.update(context)
    return templates.TemplateResponse(request=request, name=template, context=base)


def require_draft(draft_id: str):
    draft = get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="整理草稿不存在")
    payload = draft.get("payload", {})
    # v0.1.1 草稿没有 organization_mode；保持旧版“Season 目录”语义，避免升级后预览结果悄悄变化。
    if "organization_mode" not in payload:
        payload["organization_mode"] = "seasoned"
    # v0.1.2 drafts did not have these switches. Preserve their old output
    # semantics unless the user explicitly enables the v0.1.3 options.
    payload.setdefault("ugreen_compat", False)
    payload.setdefault("auto_episode_thumbs", False)
    episodes = payload.get("episodes", [])
    first_source = episodes[0].get("source", "") if episodes else ""
    for kind in ("poster", "fanart"):
        payload.setdefault(f"{kind}_source", first_source)
        payload.setdefault(f"selected_{kind}_thumb", "")
    return draft


def require_append_draft(draft_id: str):
    draft = get_draft(draft_id)
    if not draft or draft.get("payload", {}).get("kind") != "append":
        raise HTTPException(status_code=404, detail="增量追加草稿不存在")
    return draft


def apply_form_fields(payload: dict, form) -> None:
    mode = str(form.get("mode", payload.get("mode", "organize")))
    payload["mode"] = mode if mode in {"organize", "metadata_only"} else "organize"
    organization_mode = str(form.get("organization_mode", payload.get("organization_mode", "flat")))
    payload["organization_mode"] = organization_mode if organization_mode in {"flat", "seasoned"} else "flat"
    payload["ugreen_compat"] = str(form.get("ugreen_compat", "0")) == "1"
    payload["auto_episode_thumbs"] = str(form.get("auto_episode_thumbs", "0")) == "1"
    payload["series_title"] = str(form.get("series_title", payload.get("series_title", ""))).strip()
    payload["series_plot"] = str(form.get("series_plot", payload.get("series_plot", ""))).strip()
    payload["year"] = str(form.get("year", payload.get("year", ""))).strip()
    payload["genres"] = str(form.get("genres", payload.get("genres", ""))).strip()
    payload["output_parent"] = str(form.get("output_parent", payload.get("output_parent", ""))).strip("/\\")
    payload["season"] = max(1, int(str(form.get("season", payload.get("season", 1))) or "1"))
    if payload["organization_mode"] == "flat":
        payload["season"] = 1
    payload["season_title"] = str(form.get("season_title", payload.get("season_title", f"Season {payload['season']:02d}"))).strip()
    episode_sources = {ep.get("source", "") for ep in payload.get("episodes", [])}
    for kind in ("poster", "fanart"):
        source_key = f"{kind}_source"
        selected_key = f"selected_{kind}_thumb"
        requested_source = str(form.get(source_key, payload.get(source_key, ""))).strip()
        if requested_source in episode_sources:
            payload[source_key] = requested_source
        selected = form.get(selected_key)
        if selected is not None:
            payload[selected_key] = str(selected).strip()
    for idx, ep in enumerate(payload.get("episodes", [])):
        ep["episode"] = max(1, int(str(form.get(f"episode_{idx}", ep.get("episode", idx + 1))) or idx + 1))
        ep["title"] = str(form.get(f"title_{idx}", ep.get("title", ""))).strip()
        ep["plot"] = str(form.get(f"plot_{idx}", ep.get("plot", ""))).strip()
        ep["aired"] = str(form.get(f"aired_{idx}", ep.get("aired", ""))).strip()
        selected = form.get(f"selected_thumb_{idx}")
        if selected is not None:
            ep["selected_thumb"] = str(selected).strip()


def enrich_thumbnails(draft_id: str, payload: dict) -> dict:
    for idx, ep in enumerate(payload.get("episodes", [])):
        folder = THUMB_ROOT / draft_id / "episodes" / str(idx)
        thumbs = []
        if folder.exists():
            for file in sorted(folder.glob("candidate_*.jpg")):
                thumbs.append({
                    "filename": file.name,
                    "url": f"/thumb-cache/{draft_id}/episodes/{idx}/{file.name}",
                })
        ep["thumbs"] = thumbs
    for kind in ("poster", "fanart"):
        folder = THUMB_ROOT / draft_id / "artwork" / kind
        thumbs = []
        if folder.exists():
            for file in sorted(folder.glob("candidate_*.jpg")):
                thumbs.append({
                    "filename": file.name,
                    "url": f"/thumb-cache/{draft_id}/artwork/{kind}/{file.name}",
                })
        payload[f"{kind}_thumbs"] = thumbs
    return payload


@app.get("/health")
def health():
    return {"status": "ok", "media_root": str(MEDIA_ROOT)}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(
        request,
        "index.html",
        drafts=list_drafts(8),
        tasks=list_tasks(8),
    )


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request, path: str = ""):
    try:
        data = scan_directory(path)
    except (MediaPathError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return render(request, "browse.html", **data)


@app.get("/collections", response_class=HTMLResponse)
def collections_page(request: Request):
    return render(request, "collections.html", collections=list_collections())


@app.get("/collection", response_class=HTMLResponse)
def collection_detail(request: Request, path: str):
    try:
        collection = load_collection(path)
    except (CollectionError, MediaPathError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return render(request, "collection_detail.html", collection=collection)


@app.post("/collection/update")
async def collection_update(request: Request):
    form = await request.form()
    path = str(form.get("path", ""))
    try:
        operations = update_collection_metadata(
            path,
            title=str(form.get("title", "")),
            plot=str(form.get("plot", "")),
            year=str(form.get("year", "")),
            genres=str(form.get("genres", "")),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"更新集合信息失败：{exc}") from exc
    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, f"更新集合信息：{path}", operations, "success")
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/collection/episode/update")
async def collection_episode_update(request: Request):
    form = await request.form()
    path = str(form.get("path", ""))
    video = str(form.get("video", ""))
    try:
        operations = update_episode_metadata(
            path,
            video,
            title=str(form.get("title", "")),
            plot=str(form.get("plot", "")),
            aired=str(form.get("aired", "")),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"更新单集信息失败：{exc}") from exc
    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, f"更新单集信息：{Path(video).name}", operations, "success")
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/collection/repair")
async def collection_repair(request: Request):
    form = await request.form()
    path = str(form.get("path", ""))
    try:
        operations = repair_collection(
            path,
            repair_tvshow=str(form.get("repair_tvshow", "0")) == "1",
            repair_episode_nfo=str(form.get("repair_episode_nfo", "0")) == "1",
            repair_episode_thumbs=str(form.get("repair_episode_thumbs", "0")) == "1",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"修复集合失败：{exc}") from exc
    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, f"修复集合完整性：{path}", operations, "success")
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.get("/collection/add", response_class=HTMLResponse)
def collection_add_page(request: Request, collection: str, path: str = ""):
    try:
        target = load_collection(collection)
        data = scan_directory(path)
    except (CollectionError, MediaPathError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return render(request, "collection_add.html", collection=target, **data)


@app.post("/collection/add/create")
async def collection_add_create(request: Request):
    form = await request.form()
    collection = str(form.get("collection", ""))
    selected = [str(v) for v in form.getlist("selected")]
    if not selected:
        return RedirectResponse(f"/collection/add?collection={quote(collection, safe='')}&error=no-selection", status_code=303)
    try:
        payload = build_append_payload(collection, selected)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    draft_id = uuid.uuid4().hex[:12]
    save_draft(draft_id, payload)
    return RedirectResponse(f"/append/{draft_id}/edit", status_code=303)


@app.get("/append/{draft_id}/edit", response_class=HTMLResponse)
def append_edit(request: Request, draft_id: str):
    draft = require_append_draft(draft_id)
    return render(request, "append_edit.html", draft=draft, payload=draft["payload"])


@app.post("/append/{draft_id}/save")
async def append_save(request: Request, draft_id: str):
    draft = require_append_draft(draft_id)
    form = await request.form()
    apply_append_form(draft["payload"], form)
    save_draft(draft_id, draft["payload"])
    action = str(form.get("action", "save"))
    if action == "preview":
        return RedirectResponse(f"/append/{draft_id}/preview", status_code=303)
    return RedirectResponse(f"/append/{draft_id}/edit?saved=1", status_code=303)


@app.get("/append/{draft_id}/preview", response_class=HTMLResponse)
def append_preview_page(request: Request, draft_id: str):
    draft = require_append_draft(draft_id)
    try:
        plan = preview_append(draft["payload"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return render(request, "append_preview.html", draft=draft, plan=plan)


@app.post("/append/{draft_id}/execute")
def append_execute(draft_id: str):
    draft = require_append_draft(draft_id)
    task_id = uuid.uuid4().hex[:12]
    collection_path = draft["payload"].get("collection_path", "")
    create_task(task_id, f"向集合增量追加视频：{collection_path}", [], "running")
    try:
        operations = execute_append(draft["payload"])
        update_task(task_id, status="success", operations=operations)
        save_draft(draft_id, draft["payload"], status="executed")
    except (CollectionConflictError, CollectionError) as exc:
        update_task(task_id, status="failed", error=str(exc))
    except Exception as exc:
        update_task(task_id, status="failed", error=str(exc))
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/drafts/create")
async def create_draft_route(request: Request):
    form = await request.form()
    selected = [str(v) for v in form.getlist("selected")]
    if not selected:
        return RedirectResponse("/browse?error=no-selection", status_code=303)
    try:
        payload = default_draft(selected)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    draft_id = uuid.uuid4().hex[:12]
    save_draft(draft_id, payload)
    return RedirectResponse(f"/drafts/{draft_id}/edit", status_code=303)


@app.get("/drafts/{draft_id}/edit", response_class=HTMLResponse)
def edit_draft(request: Request, draft_id: str):
    draft = require_draft(draft_id)
    payload = enrich_thumbnails(draft_id, draft["payload"])
    return render(request, "draft_edit.html", draft=draft, payload=payload)


@app.post("/drafts/{draft_id}/save")
async def save_draft_route(request: Request, draft_id: str):
    draft = require_draft(draft_id)
    payload = draft["payload"]
    form = await request.form()

    apply_form_fields(payload, form)

    for kind in ("poster", "fanart"):
        upload = form.get(kind)
        if isinstance(upload, UploadFile) and upload.filename:
            content = await upload.read()
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"{kind} 图片不能超过 20MB")
            cached = save_uploaded_artwork(draft_id, kind, upload.filename, content)
            payload[f"{kind}_cache"] = cached
            payload[f"selected_{kind}_thumb"] = ""

    save_draft(draft_id, payload)
    action = str(form.get("action", "save"))
    if action == "preview":
        return RedirectResponse(f"/drafts/{draft_id}/preview", status_code=303)
    return RedirectResponse(f"/drafts/{draft_id}/edit?saved=1", status_code=303)


@app.post("/drafts/{draft_id}/thumbs/{episode_index}")
async def create_thumbs(request: Request, draft_id: str, episode_index: int):
    draft = require_draft(draft_id)
    form = await request.form()
    apply_form_fields(draft["payload"], form)
    save_draft(draft_id, draft["payload"])
    episodes = draft["payload"].get("episodes", [])
    if episode_index < 0 or episode_index >= len(episodes):
        raise HTTPException(status_code=404, detail="集数不存在")
    try:
        generate_candidates(draft_id, episode_index, episodes[episode_index]["source"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成缩略图失败：{exc}") from exc
    return RedirectResponse(f"/drafts/{draft_id}/edit#episode-{episode_index}", status_code=303)


@app.post("/drafts/{draft_id}/artwork/{kind}")
async def create_artwork_thumbs(request: Request, draft_id: str, kind: str):
    if kind not in {"poster", "fanart"}:
        raise HTTPException(status_code=404, detail="图片类型不存在")
    draft = require_draft(draft_id)
    form = await request.form()
    apply_form_fields(draft["payload"], form)
    source = draft["payload"].get(f"{kind}_source") or ""
    if not source:
        raise HTTPException(status_code=400, detail="请先选择用于截图的视频")
    save_draft(draft_id, draft["payload"])
    try:
        generate_artwork_candidates(draft_id, kind, source)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成{kind}候选图失败：{exc}") from exc
    return RedirectResponse(f"/drafts/{draft_id}/edit#series-artwork", status_code=303)


@app.get("/drafts/{draft_id}/preview", response_class=HTMLResponse)
def preview_draft(request: Request, draft_id: str):
    draft = require_draft(draft_id)
    try:
        plan = preview_plan(draft["payload"], draft_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return render(request, "preview.html", draft=draft, plan=plan)


@app.post("/drafts/{draft_id}/execute")
def execute_draft_route(draft_id: str):
    draft = require_draft(draft_id)
    task_id = uuid.uuid4().hex[:12]
    series_name = draft['payload'].get('series_title') or '未命名集合'
    compat_suffix = "（绿联兼容）" if draft['payload'].get('organization_mode') == 'flat' and draft['payload'].get('ugreen_compat') else ""
    summary = f"整理视频集合：{series_name}{compat_suffix}"
    create_task(task_id, summary, [], "running")
    try:
        operations = execute_plan(draft["payload"], draft_id)
        update_task(task_id, status="success", operations=operations)
        save_draft(draft_id, draft["payload"], status="executed")
    except PlanConflictError as exc:
        update_task(task_id, status="failed", error=str(exc))
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    except Exception as exc:
        update_task(task_id, status="failed", error=str(exc))
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.get("/tasks", response_class=HTMLResponse)
def task_list(request: Request):
    return render(request, "tasks.html", tasks=list_tasks(100))


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return render(request, "task_detail.html", task=task)


@app.post("/tasks/{task_id}/undo")
def undo_task_route(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "success":
        raise HTTPException(status_code=400, detail="只有成功任务可以撤销")
    errors = undo_operations(task["operations"])
    if errors:
        update_task(task_id, status="undo_failed", error="；".join(errors))
    else:
        update_task(task_id, status="undone", error=None)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)
