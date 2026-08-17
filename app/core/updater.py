from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from app.config import APP_RUNTIME_ROOT, UPDATE_REPOSITORY
from app.version import APP_VERSION

RUNTIME_API = int(os.getenv("NMM_RUNTIME_API", "1"))
RUNTIME_MANAGED = os.getenv("NMM_RUNTIME_MANAGED", "0") == "1"
USER_AGENT = "nas-media-manager-updater/1"
RELEASE_API = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
MANIFEST_ASSET = "update-manifest.json"


class UpdateError(RuntimeError):
    pass


class RuntimeUpgradeRequired(UpdateError):
    pass


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.strip().lstrip("v").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            break
    return tuple(parts) or (0,)


def _read_url(url: str, *, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/octet-stream",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"访问更新服务器失败：{exc}") from exc


def _read_json(url: str, *, timeout: int = 20) -> dict:
    try:
        return json.loads(_read_url(url, timeout=timeout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("更新服务器返回了无法解析的数据") from exc


def _release_assets(release: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for asset in release.get("assets", []):
        name = str(asset.get("name", ""))
        if name:
            result[name] = asset
    return result


def fetch_latest_manifest() -> dict:
    release = _read_json(RELEASE_API)
    assets = _release_assets(release)
    manifest_asset = assets.get(MANIFEST_ASSET)
    if not manifest_asset:
        raise UpdateError("最新版本没有提供轻量更新清单")

    manifest = _read_json(str(manifest_asset.get("browser_download_url", "")))
    archive_name = str(manifest.get("archive", ""))
    archive_asset = assets.get(archive_name)
    if not archive_name or not archive_asset:
        raise UpdateError("更新清单对应的更新包不存在")

    manifest["archive_url"] = str(archive_asset.get("browser_download_url", ""))
    manifest["release_url"] = str(release.get("html_url", ""))
    manifest["release_name"] = str(release.get("name") or release.get("tag_name") or "")
    manifest["published_at"] = str(release.get("published_at", ""))
    return manifest


def check_for_update() -> dict:
    manifest = fetch_latest_manifest()
    latest = str(manifest.get("version", "")).strip()
    required_runtime = int(manifest.get("runtime_api", 1))
    if not latest:
        raise UpdateError("更新清单缺少版本号")

    return {
        **manifest,
        "current_version": APP_VERSION,
        "latest_version": latest,
        "has_update": _version_key(latest) > _version_key(APP_VERSION),
        "runtime_upgrade_required": required_runtime > RUNTIME_API,
        "runtime_api": RUNTIME_API,
        "managed_runtime": RUNTIME_MANAGED,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise UpdateError("更新包包含非法路径")
            if member.issym() or member.islnk():
                raise UpdateError("更新包不允许包含符号链接")
            resolved = (destination / member_path).resolve()
            try:
                resolved.relative_to(destination)
            except ValueError as exc:
                raise UpdateError("更新包路径越界") from exc
        tf.extractall(destination)


def _atomic_switch(target: Path) -> None:
    APP_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    current = APP_RUNTIME_ROOT / "current"
    pending = APP_RUNTIME_ROOT / ".current-next"
    if pending.exists() or pending.is_symlink():
        pending.unlink()
    pending.symlink_to(target, target_is_directory=True)
    os.replace(pending, current)


def _request_restart() -> None:
    flag = APP_RUNTIME_ROOT / "restart.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()


def installed_versions() -> list[dict]:
    versions_root = APP_RUNTIME_ROOT / "versions"
    current_target: Path | None = None
    current = APP_RUNTIME_ROOT / "current"
    if current.is_symlink():
        try:
            current_target = current.resolve()
        except OSError:
            current_target = None

    result: list[dict] = []
    if versions_root.exists():
        for folder in versions_root.iterdir():
            if not folder.is_dir():
                continue
            version_file = folder / "VERSION"
            if not version_file.exists():
                continue
            version = version_file.read_text(encoding="utf-8").strip() or folder.name
            result.append({
                "version": version,
                "path": str(folder),
                "current": current_target == folder.resolve(),
            })
    result.sort(key=lambda item: _version_key(str(item["version"])), reverse=True)
    return result


def install_latest_update() -> dict:
    if not RUNTIME_MANAGED:
        raise UpdateError("当前不是轻量更新 Runtime 模式，请先完成一次 Docker Runtime 迁移")

    manifest = fetch_latest_manifest()
    version = str(manifest.get("version", "")).strip()
    archive_url = str(manifest.get("archive_url", ""))
    expected_sha = str(manifest.get("sha256", "")).lower().strip()
    required_runtime = int(manifest.get("runtime_api", 1))

    if required_runtime > RUNTIME_API:
        raise RuntimeUpgradeRequired(
            f"v{version} 需要 Runtime API {required_runtime}，当前为 {RUNTIME_API}，请更新 Docker Runtime"
        )
    if not version or not archive_url or len(expected_sha) != 64:
        raise UpdateError("更新清单不完整")
    if _version_key(version) <= _version_key(APP_VERSION):
        raise UpdateError("当前已经是最新版本")

    versions_root = APP_RUNTIME_ROOT / "versions"
    versions_root.mkdir(parents=True, exist_ok=True)
    target = versions_root / version

    with tempfile.TemporaryDirectory(prefix="nmm-update-", dir=str(APP_RUNTIME_ROOT)) as tmp_name:
        tmp = Path(tmp_name)
        archive = tmp / "update.tar.gz"
        archive.write_bytes(_read_url(archive_url, timeout=120))
        actual_sha = _sha256(archive)
        if actual_sha.lower() != expected_sha:
            raise UpdateError("更新包 SHA256 校验失败，已取消安装")

        extracted = tmp / "extracted"
        extracted.mkdir()
        _safe_extract(archive, extracted)
        if not (extracted / "app").is_dir() or not (extracted / "VERSION").is_file():
            raise UpdateError("更新包结构不完整")
        packaged_version = (extracted / "VERSION").read_text(encoding="utf-8").strip()
        if packaged_version != version:
            raise UpdateError("更新包版本与更新清单不一致")

        staged = versions_root / f".{version}.staging"
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(extracted, staged)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staged, target)

    _atomic_switch(target)
    _request_restart()
    return {
        "version": version,
        "restart_requested": True,
        "archive": str(manifest.get("archive", "")),
    }


def rollback_to(version: str) -> dict:
    if not RUNTIME_MANAGED:
        raise UpdateError("当前不是轻量更新 Runtime 模式")
    safe_version = version.strip()
    if not safe_version or "/" in safe_version or "\\" in safe_version or ".." in safe_version:
        raise UpdateError("回滚版本号非法")

    target = APP_RUNTIME_ROOT / "versions" / safe_version
    if not target.is_dir() or not (target / "VERSION").is_file():
        raise UpdateError("指定版本未安装")
    packaged_version = (target / "VERSION").read_text(encoding="utf-8").strip()
    if packaged_version != safe_version:
        raise UpdateError("版本目录校验失败")
    if safe_version == APP_VERSION:
        raise UpdateError("当前已经运行该版本")

    _atomic_switch(target)
    _request_restart()
    return {"version": safe_version, "restart_requested": True}
