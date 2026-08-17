# 绿联 NAS Docker 部署

从 v0.1.5 开始，推荐使用 GitHub Container Registry（GHCR）镜像部署。GitHub `main` 分支代码通过自动测试后，会自动构建 `linux/amd64` 和 `linux/arm64` 镜像并推送到：

```text
ghcr.io/rosenray/nas-media-manager
```

这样 NAS 不再需要保存完整源码，也不需要每次重新构建镜像。

## 1. 推荐 Compose

在绿联 NAS 的 Docker 项目目录保存下面的 `docker-compose.yml`：

```yaml
services:
  nas-media-manager:
    image: ghcr.io/rosenray/nas-media-manager:latest
    container_name: nas-media-manager
    restart: unless-stopped
    ports:
      - "18765:8000"
    environment:
      MEDIA_ROOT: /media
      DATA_ROOT: /data
    volumes:
      - /你的NAS真实视频目录:/media
      - ./data:/data
```

只修改左侧 `/你的NAS真实视频目录`，右侧 `/media` 和 `/data` 保持不变。

`./data:/data` 会保存 SQLite、任务记录、草稿图片和缩略图缓存。更新 Docker 镜像时不要删除这个目录。

## 2. 第一次部署

在 UGOS Pro Docker 中创建项目并使用上面的 Compose，然后拉取并启动镜像。

如果 NAS 提示无法拉取 `ghcr.io/rosenray/nas-media-manager:latest`，先确认 GitHub Container Registry 中 `nas-media-manager` 包允许当前 NAS 拉取。对于公开仓库，建议将容器包设置为 Public，这样 NAS 无需额外登录 GHCR。

启动后访问：

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

## 3. 以后更新版本

后续代码提交到 `main` 后，GitHub Actions 会先运行测试。测试通过后自动构建并推送新镜像。

### 绿联 Docker 界面

以后只需要在 Docker 中更新 / 重新拉取 `nas-media-manager` 镜像，然后重新创建或启动容器即可，不需要重新上传源码。

### 命令行更新

如果在 NAS 主机终端使用 Docker Compose：

```bash
docker compose pull
docker compose up -d
```

也可以：

```bash
docker compose up -d --pull always
```

## 4. 版本回退

默认使用：

```yaml
image: ghcr.io/rosenray/nas-media-manager:latest
```

如果新版有问题，可以临时指定版本，例如：

```yaml
image: ghcr.io/rosenray/nas-media-manager:0.1.5
```

然后重新拉取和启动：

```bash
docker compose pull
docker compose up -d
```

程序数据仍保存在 `/data` 挂载目录中。

## 5. 镜像标签

每次 `main` 发布会生成：

```text
latest
VERSION 文件中的版本号，例如 0.1.5
```

因此：

```text
ghcr.io/rosenray/nas-media-manager:latest
ghcr.io/rosenray/nas-media-manager:0.1.5
```

都会指向对应构建结果。

## 6. CPU 架构

自动构建同时支持：

```text
linux/amd64
linux/arm64
```

Docker 会根据 NAS CPU 架构自动选择对应镜像。

## 7. 确认媒体目录映射

如果网页能打开但媒体目录为空，进入容器终端检查：

```bash
ls -lah /media
```

如果 `/media` 为空，优先检查 Compose 左侧 NAS 路径是否正确。

## 8. 本地源码构建

仓库仍保留 `Dockerfile`，开发调试时可以使用：

```bash
docker compose -f docker-compose.local.yml up -d --build
```

日常 NAS 部署不再需要这一方式。
