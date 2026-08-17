from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.updater import (
    RUNTIME_API,
    RUNTIME_MANAGED,
    RuntimeUpgradeRequired,
    UpdateError,
    check_for_update,
    install_latest_update,
    installed_versions,
    rollback_to,
)
from app.main import app, render, templates
from app.version import APP_VERSION

# app.main remains the core application module. The stable Docker Runtime launches
# this wrapper so update-specific routes can evolve with the lightweight app package.
app.version = APP_VERSION
templates.env.globals["app_version"] = APP_VERSION


def _settings_context(*, latest: dict | None = None, update_error: str = "") -> dict:
    return {
        "app_version": APP_VERSION,
        "runtime_api": RUNTIME_API,
        "managed_runtime": RUNTIME_MANAGED,
        "installed": installed_versions(),
        "latest": latest,
        "update_error": update_error,
    }


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, check: int = 0):
    latest = None
    update_error = ""
    if check:
        try:
            latest = check_for_update()
        except UpdateError as exc:
            update_error = str(exc)
    return render(request, "settings.html", **_settings_context(latest=latest, update_error=update_error))


@app.post("/settings/update", response_class=HTMLResponse)
def settings_update(request: Request):
    try:
        result = install_latest_update()
    except RuntimeUpgradeRequired as exc:
        return render(request, "settings.html", **_settings_context(update_error=str(exc)))
    except UpdateError as exc:
        return render(request, "settings.html", **_settings_context(update_error=str(exc)))
    return RedirectResponse(f"/settings?updated={quote(result['version'], safe='')}", status_code=303)


@app.post("/settings/rollback", response_class=HTMLResponse)
async def settings_rollback(request: Request):
    form = await request.form()
    version = str(form.get("version", "")).strip()
    try:
        result = rollback_to(version)
    except UpdateError as exc:
        return render(request, "settings.html", **_settings_context(update_error=str(exc)))
    return RedirectResponse(f"/settings?rollback={quote(result['version'], safe='')}", status_code=303)
