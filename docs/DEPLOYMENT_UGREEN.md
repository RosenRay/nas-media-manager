# 绿联 NAS Docker 部署

## 1. 准备项目目录

将仓库克隆或下载到绿联 NAS 的 Docker 项目目录，例如：

```text
Docker/nas-media-manager/
```

确保项目根目录直接包含：

```text
Dockerfile
docker-compose.yml
requirements.txt
app/
```

## 2. 修改媒体目录映射

编辑 `docker-compose.yml`：

```yaml
services:
  nas-media-manager:
    build: .
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

重点：

- 左侧 `/你的NAS真实视频目录` 必须替换成绿联 NAS 上实际存在的视频目录。
- 右侧 `/media` 保持不变。
- `/data` 用于 SQLite、上传图片和缩略图缓存。
- 媒体目录需要可写权限，因为程序会执行重命名、移动、创建 NFO 和图片。

## 3. 在绿联 Docker 创建项目

在 UGOS Pro：

1. 打开 Docker。
2. 进入“项目”。
3. 创建项目并选择本仓库所在目录。
4. 确认 Compose 内容。
5. 执行构建并启动。

第一次会安装 Python 依赖和 FFmpeg，需要能够访问对应软件源。

## 4. 访问

默认端口：

```text
http://NAS-IP:18765
```

健康检查：

```text
http://NAS-IP:18765/health
```

正常返回示例：

```json
{"status":"ok","media_root":"/media"}
```

## 5. 确认媒体目录映射

如果页面目录为空，优先进入容器终端检查：

```bash
ls -lah /media
```

如果 `/media` 为空，通常意味着 Compose 左侧 NAS 路径填写错误，而不是程序扫描失败。

## 6. 首次使用建议

不要一开始映射整个正式媒体库。先建立测试目录：

```text
MediaManager-Test/
├── test01.mp4
├── test02.mp4
└── test03.mp4
```

验证完整流程：

```text
扫描
→ 创建集合
→ 编辑元数据
→ 生成海报/背景图/单集图
→ 预览
→ 执行
→ 绿联影视中心重新扫描
→ 确认归组
→ 测试撤销
```

确认无误后再扩大媒体目录范围。

## 7. 更新版本

建议每个版本使用独立项目目录，并保留旧版本 `data/` 的备份。

更新后要重新构建镜像，而不是只重启旧容器，否则 Docker 可能继续运行旧镜像中的源码。
