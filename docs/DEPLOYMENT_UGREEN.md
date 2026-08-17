# 绿联 NAS Docker 部署

从 v0.1.7 开始，推荐使用“稳定 Docker Runtime + 应用内轻量更新”的方式部署。

这样做的目的，是避免每次仅修改 Python / HTML / CSS 时，都重新下载包含 Python、FFmpeg 和系统依赖的大型 Docker 镜像。

## 1. 推荐 Compose

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
      - /你的NAS真实视频目录:/media
      - ./data:/data
```

只需要修改左侧 `/你的NAS真实视频目录`。右侧 `/media` 和 `/data` 保持不变。

`./data:/data` 会持久化：

- SQLite 数据库
- 草稿和任务记录
- 上传图片与缩略图缓存
- `/data/app_runtime/versions/` 中的应用版本
- 当前版本指针与回滚信息

因此升级或重新创建容器时不要删除 `./data`。

## 2. 从 v0.1.6 及以前迁移

这是切换到轻量更新机制后需要做的**最后一次大型 Docker 更新**。

如果使用 Compose：

```bash
docker compose pull
docker compose up -d
```

确认最终使用的镜像为：

```text
ghcr.io/rosenray/nas-media-manager:runtime-1
```

Runtime 第一次启动时会把镜像内自带的当前应用版本复制到：

```text
/data/app_runtime/versions/<version>/
```

并创建：

```text
/data/app_runtime/current
```

作为当前运行版本。

原来的 `/data/media_manager.db`、草稿、任务记录和媒体目录不会被迁移或删除。

## 3. 启动验证

访问：

```text
http://NAS-IP:18765
```

健康检查：

```text
http://NAS-IP:18765/health
```

正常返回类似：

```json
{"status":"ok","media_root":"/media"}
```

进入页面底部或顶部导航后，应能看到：

```text
设置
```

设置页中应显示：

```text
轻量更新 Runtime ✓
Runtime API 1
```

## 4. 以后普通版本怎么更新

普通 Python / HTML / CSS / JS / NFO 逻辑更新，不再执行：

```bash
docker compose pull
```

直接在浏览器中：

```text
设置 → 检查更新 → 立即轻量更新
```

应用会下载 GitHub Release 中的小型更新包，校验 SHA256 后安装到新的版本目录，并由 Runtime Launcher 自动重启 Uvicorn。

通常只有几秒钟 Web 服务不可访问，Docker 容器本身不会重启。

详细机制见：[轻量更新机制](LIGHTWEIGHT_UPDATES.md)。

## 5. 什么时候还需要更新 Docker

只有运行环境变化时，例如：

- Python 基础镜像升级
- FFmpeg / 系统依赖变化
- `requirements.txt` 增加或升级依赖
- Runtime Launcher 修改
- `RUNTIME_API` 升级

应用检查更新时，如果发现新版本需要更高 Runtime API，会停止轻量更新并提示先升级 Docker Runtime。

例如未来 Runtime API 升级到 2，Compose 才需要改为：

```yaml
image: ghcr.io/rosenray/nas-media-manager:runtime-2
```

然后再执行：

```bash
docker compose pull
docker compose up -d
```

## 6. 应用版本回滚

设置页会读取：

```text
/data/app_runtime/versions/
```

中已安装的版本。

选择旧版本并点击“回滚”后，仅切换应用代码并重启 Uvicorn，不会修改：

- 数据库
- 草稿
- 缩略图
- 任务历史
- `/media` 中的视频和 NFO

## 7. Runtime 镜像标签

当前稳定 Runtime：

```text
ghcr.io/rosenray/nas-media-manager:runtime-1
```

GitHub Actions 只有检测到这些文件变化时才重新构建 Runtime：

```text
Dockerfile
requirements.txt
runtime/
RUNTIME_API
```

每个 Runtime 同时构建：

```text
linux/amd64
linux/arm64
```

Docker 会根据 NAS CPU 架构自动选择。

## 8. 媒体目录为空怎么办

如果网页可以打开但媒体目录为空，进入容器终端检查：

```bash
ls -lah /media
```

如果 `/media` 为空，优先检查 Compose 左侧 NAS 路径是否正确。

## 9. 国内网络较慢

v0.1.7 已把高频更新从大型 GHCR 镜像降为小型 GitHub Release 更新包，因此大多数更新的数据量会明显降低。

当前轻量更新源仍然是 GitHub Release。如果所在网络访问 GitHub 本身非常不稳定，后续计划增加：

- 自定义更新源
- 国内镜像地址
- 手动上传轻量更新包

## 10. 本地源码开发

开发调试仍可使用：

```bash
docker compose -f docker-compose.local.yml up -d --build
```

`docker-compose.local.yml` 会直接挂载本地 `app/`，不使用 `/data/app_runtime/current`，因此代码修改可以通过 Uvicorn reload 立即生效。
