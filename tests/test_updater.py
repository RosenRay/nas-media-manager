from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from app.core import updater


def make_bundle(tmp_path: Path, version: str = "0.1.8") -> tuple[bytes, str]:
    source = tmp_path / "bundle-src"
    (source / "app").mkdir(parents=True)
    (source / "app" / "__init__.py").write_text("", encoding="utf-8")
    (source / "app" / "marker.txt").write_text(f"version={version}\n", encoding="utf-8")
    (source / "VERSION").write_text(version + "\n", encoding="utf-8")

    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(source / "app", arcname="app")
        tf.add(source / "VERSION", arcname="VERSION")
    data = archive.read_bytes()
    import hashlib

    return data, hashlib.sha256(data).hexdigest()


def test_version_key_orders_semver_like_versions():
    assert updater._version_key("0.1.10") > updater._version_key("0.1.9")
    assert updater._version_key("v1.2.3") == (1, 2, 3)


def test_safe_extract_rejects_parent_traversal(tmp_path: Path):
    archive = tmp_path / "bad.tar.gz"
    payload = b"bad"
    info = tarfile.TarInfo("../escape.txt")
    info.size = len(payload)
    with tarfile.open(archive, "w:gz") as tf:
        tf.addfile(info, io.BytesIO(payload))

    with pytest.raises(updater.UpdateError):
        updater._safe_extract(archive, tmp_path / "out")


def test_install_switches_current_and_requests_restart(tmp_path: Path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    bundle, sha256 = make_bundle(tmp_path, "0.1.8")

    monkeypatch.setattr(updater, "APP_RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(updater, "RUNTIME_MANAGED", True)
    monkeypatch.setattr(updater, "APP_VERSION", "0.1.7")
    monkeypatch.setattr(
        updater,
        "fetch_latest_manifest",
        lambda: {
            "version": "0.1.8",
            "runtime_api": 1,
            "archive": "nas-media-manager-update-0.1.8.tar.gz",
            "archive_url": "https://example.invalid/update.tar.gz",
            "sha256": sha256,
        },
    )
    monkeypatch.setattr(updater, "_read_url", lambda url, timeout=20: bundle)

    result = updater.install_latest_update()

    assert result["version"] == "0.1.8"
    current = runtime_root / "current"
    assert current.is_symlink()
    assert (current.resolve() / "VERSION").read_text(encoding="utf-8").strip() == "0.1.8"
    assert (runtime_root / "restart.flag").exists()


def test_install_rejects_runtime_upgrade(tmp_path: Path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    monkeypatch.setattr(updater, "APP_RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(updater, "RUNTIME_MANAGED", True)
    monkeypatch.setattr(updater, "RUNTIME_API", 1)
    monkeypatch.setattr(
        updater,
        "fetch_latest_manifest",
        lambda: {
            "version": "0.2.0",
            "runtime_api": 2,
            "archive": "x.tar.gz",
            "archive_url": "https://example.invalid/x.tar.gz",
            "sha256": "0" * 64,
        },
    )

    with pytest.raises(updater.RuntimeUpgradeRequired):
        updater.install_latest_update()


def test_rollback_switches_to_installed_version(tmp_path: Path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    versions = runtime_root / "versions"
    old = versions / "0.1.6"
    current_version = versions / "0.1.7"
    old.mkdir(parents=True)
    current_version.mkdir(parents=True)
    (old / "VERSION").write_text("0.1.6\n", encoding="utf-8")
    (current_version / "VERSION").write_text("0.1.7\n", encoding="utf-8")
    (runtime_root / "current").symlink_to(current_version, target_is_directory=True)

    monkeypatch.setattr(updater, "APP_RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(updater, "RUNTIME_MANAGED", True)
    monkeypatch.setattr(updater, "APP_VERSION", "0.1.7")

    result = updater.rollback_to("0.1.6")

    assert result["version"] == "0.1.6"
    assert (runtime_root / "current").resolve() == old.resolve()
    assert (runtime_root / "restart.flag").exists()


def test_runtime_launcher_uses_runtime_aware_entrypoint():
    launcher = Path("runtime/launcher.py").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "app.runtime_main:app" in launcher
    assert 'CMD ["python", "/opt/runtime/launcher.py"]' in dockerfile
    assert "nas-media-manager:runtime-1" in compose
