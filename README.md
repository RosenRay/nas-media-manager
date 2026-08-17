# NAS Media Manager

面向 NAS 私人视频的本地媒体整理与 NFO 元数据管理工具。

当前版本：**v0.1.5**  
当前重点：**绿联 NAS / UGOS Pro + 影视中心兼容输出 + 家庭影像批量整理**

> 当前阶段不接入 AI，也不处理电脑本地文件。工具只操作 Docker 映射到 `/media` 的 NAS 文件，优先把“扫描 → 整理 → NFO / 图片生成 → 绿联影视中心识别”这条基础链路做稳定。

## 适合什么场景

传统影视刮削器擅长电影和电视剧，但家庭录像、旅行 Vlog、课程、自己拍摄的视频通常没有在线元数据。NAS Media Manager 用于把这些内容整理成媒体中心更容易读取的本地媒资结构。

```text
NAS 原始视频
    ↓
目录扫描 / 批量选择
    ↓
视频集合编排
    ↓
重命名 / 移动 / Episode 编号
    ↓
生成 NFO + poster + fanart + 单集图片
    ↓
绿联影视中心重新扫描
    ↓
形成集合 / 单集预览页面
```

## 当前能力

### 文件扫描与整理

- 浏览 Docker 映射的 NAS 媒体目录。
- 扫描常见视频格式并读取大小、修改时间、时长、分辨率和编码信息。
- 当前目录支持“全选视频”与已选数量统计。
- 自动生成 Episode 编号。
- 新建集合年份默认使用当前年份；单集日期优先使用视频文件修改日期，异常的 1970 时间会回退到当天。
- 支持人工编辑集合名称、简介、年份、Genre、单集标题、简介和日期。
- 支持“整理并生成媒资”与“仅生成媒资”。

### 批量文件夹生成集合

可以一次勾选多个已经粗略分类好的文件夹，一个文件夹对应一个集合，集合名称默认使用文件夹名。

```text
/media/
├── 图图生日/
│   ├── 001.mp4
│   └── 002.mp4
├── 海南旅行/
│   ├── IMG_001.mp4
│   └── IMG_002.mp4
└── 公园记录/
    └── video.mp4
```

批量模式会：

- 只处理所选文件夹当前层的视频，不递归合并子目录。
- 自动过滤空目录、无支持视频目录、已有 `tvshow.nfo` 的集合，以及疑似已整理的 `Season xx + SxxExx` 目录。
- 按修改时间和文件名稳定排序后自动编号。
- 执行前提供批量预览、过滤原因和冲突检查。
- 默认输出绿联兼容的 `Season 01 + SxxExx` 结构并自动生成 Episode JPG。
- 批量任务支持失败回滚和成功后整体撤销。

### 本地媒资

- 生成 `tvshow.nfo`。
- 生成 Episode NFO。
- 按季模式支持 `season.nfo`。
- `poster.jpg` / `fanart.jpg` 支持上传或从集合内指定视频截取候选画面。
- Episode 图片支持 FFmpeg 截图候选与自动补齐。

### 已整理集合维护

- 自动发现已整理集合并进入详情页维护。
- 查看 Episode、poster / fanart / NFO / JPG 完整性。
- 修改集合标题、简介、年份、Genre，并同步已有 Episode NFO 的 `showtitle`。
- 修改单集标题、简介和日期，不主动重命名已有视频。
- 向已有集合增量添加新视频，从当前最大 Episode + 1 自动编号。
- 检查缺失 NFO/JPG、Episode 断号和重复编号。
- 支持补齐缺失 NFO 和单集 JPG。

### 安全机制

- 新集合、增量追加和批量文件夹处理执行前都有预览与冲突检测。
- 默认不覆盖已有视频、NFO 或图片。
- SQLite 保存草稿、任务和操作记录。
- 执行中发生异常时尝试自动回滚。
- 成功任务支持撤销，删除生成文件前会校验文件是否被修改。

## 绿联兼容模式

家庭影像在界面中采用“无季集合”的概念，但底层保持绿联影视中心更稳定的 TV Episode 结构：

```text
家庭影像集合/
├── tvshow.nfo
├── poster.jpg
├── fanart.jpg
└── Season 01/
    ├── 家庭影像集合 - S01E01.mp4
    ├── 家庭影像集合 - S01E01.nfo
    ├── 家庭影像集合 - S01E01.jpg
    ├── 家庭影像集合 - S01E02.mp4
    ├── 家庭影像集合 - S01E02.nfo
    └── 家庭影像集合 - S01E02.jpg
```

这一结构已在绿联 NAS 影视中心实机验证，可将同一集合中的 Episode 正确归组。

详细说明见：[绿联影视中心兼容说明](docs/UGREEN_COMPATIBILITY.md)。

## Docker 镜像发布

仓库采用 GitHub Actions 自动发布 Docker 镜像。`main` 分支提交后：

```text
pytest
  ↓ 通过
构建 linux/amd64 + linux/arm64
  ↓
推送 GitHub Container Registry
```

镜像：

```text
ghcr.io/rosenray/nas-media-manager:latest
ghcr.io/rosenray/nas-media-manager:0.1.5
```

`latest` 用于日常更新，版本号标签用于固定版本和回退。

## 推荐部署

`docker-compose.yml` 默认直接使用 GHCR 镜像，不再要求 NAS 保存源码或本地构建：

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

把左侧 `/你的NAS真实视频目录` 替换成 NAS 实际媒体路径即可。

首次启动或更新：

```bash
docker compose pull
docker compose up -d
```

或者：

```bash
docker compose up -d --pull always
```

访问：

```text
http://NAS-IP:18765
```

健康检查：

```text
http://NAS-IP:18765/health
```

绿联 NAS 的完整步骤见：[绿联 NAS Docker 部署](docs/DEPLOYMENT_UGREEN.md)。

### 本地源码构建

开发调试仍可使用：

```bash
docker compose -f docker-compose.local.yml up -d --build
```

## 技术栈

- Python 3.12
- FastAPI
- Jinja2
- SQLite
- FFmpeg / ffprobe
- Docker / Docker Compose
- GitHub Actions / GitHub Container Registry

## 项目结构

```text
nas-media-manager/
├── .github/workflows/
│   └── tests.yml             # 自动测试 + 多架构 Docker 镜像发布
├── app/
│   ├── core/
│   │   ├── media.py
│   │   ├── nfo.py
│   │   ├── organizer.py
│   │   ├── collections.py
│   │   ├── batch.py
│   │   └── thumbnails.py
│   ├── static/
│   ├── templates/
│   ├── config.py
│   ├── db.py
│   └── main.py
├── docs/
│   ├── DEPLOYMENT_UGREEN.md
│   ├── ROADMAP.md
│   └── UGREEN_COMPATIBILITY.md
├── tests/
│   ├── test_core.py
│   └── test_batch.py
├── CHANGELOG.md
├── Dockerfile
├── docker-compose.yml
├── docker-compose.local.yml
├── requirements.txt
└── VERSION
```

## 测试

```bash
python -m pytest -q
```

GitHub Actions 会在 `main` push 和 Pull Request 时自动执行完整测试；只有 `main` 的测试通过后才发布 Docker 镜像。

## 当前限制

- 仅处理 NAS Docker 映射目录，不读取电脑本地文件。
- 批量文件夹模式只扫描所选文件夹当前层的视频，不递归子目录。
- 暂不接入 AI 大模型。
- 当前主要针对绿联影视中心验证，其他媒体平台尚未建立专门适配层。
- 不直接调用或修改绿联影视中心私有数据库。

## Roadmap

下一阶段继续优先优化日常维护体验：

- 已整理集合的海报 / 背景重新截图与替换。
- 更高效的批量单集封面确认与重新截图。
- Episode 调序 / 插入后的安全重编号方案。
- 集合扫描缓存与大媒体库性能优化。

详细计划见：[Roadmap](docs/ROADMAP.md)。

## 版本记录

见：[CHANGELOG.md](CHANGELOG.md)。
