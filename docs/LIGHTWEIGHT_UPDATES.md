# 轻量更新机制

从 v0.1.7 开始，NAS Media Manager 将“运行环境”和“应用代码”分离，解决国内网络环境下频繁拉取完整 Docker 镜像过大的问题。

## 两类更新

### 普通应用更新

适用于：

- Python 业务逻辑
- Jinja2 页面
- CSS / JavaScript
- NFO 生成规则
- UI 与交互优化

GitHub Actions 会生成：

```text
nas-media-manager-update-<version>.tar.gz
update-manifest.json
```

更新包只包含：

```text
app/
VERSION
```

NAS 不需要重新下载 Python、FFmpeg 或系统依赖。

### Docker Runtime 更新

只有以下内容变化时才需要更新 Runtime：

- Python 基础镜像
- FFmpeg / 系统依赖
- `requirements.txt`
- `runtime/launcher.py`
- `RUNTIME_API`

Runtime 镜像标签：

```text
ghcr.io/rosenray/nas-media-manager:runtime-1
```

以后 Runtime API 升级时会发布 `runtime-2`、`runtime-3` 等新标签。

## 第一次迁移

v0.1.6 及之前使用完整镜像。迁移到 v0.1.7 时需要最后一次更新 Docker：

```yaml
services:
  nas-media-manager:
    image: ghcr.io/rosenray/nas-media-manager:runtime-1
    container_name: nas-media-manager
    restart: unless-stopped
    ports:
      - "18765:8000"
    environment:
      MEDIA_ROOT: /media
      DATA_ROOT: /data
      APP_RUNTIME_ROOT: /data/app_runtime
      NMM_RUNTIME_API: "1"
    volumes:
      - /你的NAS实际视频目录:/media
      - ./data:/data
```

执行：

```bash
docker compose pull
docker compose up -d
```

已有 `/data/media_manager.db`、草稿、缩略图和任务记录仍保留。

## 后续普通更新

手机或电脑浏览器打开：

```text
设置 → 检查更新
```

发现新版本后点击：

```text
立即轻量更新
```

应用会：

1. 读取 GitHub 最新 Release 的 `update-manifest.json`。
2. 检查新版本所需 `runtime_api`。
3. 下载轻量 `tar.gz` 更新包。
4. 校验 SHA256。
5. 校验压缩包路径，拒绝目录穿越和符号链接。
6. 安装到 `/data/app_runtime/versions/<version>`。
7. 原子切换 `/data/app_runtime/current`。
8. 写入 `restart.flag`。
9. Runtime Launcher 自动重启 Uvicorn 子进程。

整个过程不重启 Docker 容器，通常只会有几秒钟 Web 服务不可访问。

## 回滚

设置页会列出保留在：

```text
/data/app_runtime/versions/
```

中的旧版本。

点击“回滚”后只切换应用代码并重启 Uvicorn，不修改：

- `/data/media_manager.db`
- 草稿与任务记录
- 上传图片和缩略图
- `/media` 中的媒体文件

> 注意：未来如果某个版本包含不可逆数据库迁移，会在版本发布时单独声明。v0.1.7 本身没有数据库结构迁移。

## 版本兼容

轻量更新包的 `update-manifest.json` 包含：

```json
{
  "version": "0.1.7",
  "runtime_api": 1,
  "archive": "nas-media-manager-update-0.1.7.tar.gz",
  "sha256": "...",
  "size": 123456,
  "commit": "..."
}
```

如果新版本要求的 `runtime_api` 高于当前 Runtime，应用会停止轻量更新，并提示先更新 Docker Runtime，避免将依赖不兼容的代码直接覆盖到现有环境。

## 发布规则

`main` 分支通过测试后：

```text
pytest
  ├─→ 生成轻量更新包 → GitHub Release
  └─→ 检测 Runtime 文件是否变化
          ├─ 无变化：不构建 Docker Runtime
          └─ 有变化：构建 amd64 + arm64 runtime-N
```

因此绝大多数日常版本不会要求 NAS 拉取大型 Docker 镜像。
