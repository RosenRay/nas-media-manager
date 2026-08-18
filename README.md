# NAS Media Manager

面向 NAS 私人视频的本地媒体整理与 NFO 元数据管理工具。

当前版本：**v0.1.8**  
当前重点：**绿联 NAS / UGOS Pro + 手机优先 + 轻量更新 + 家庭视频封面构图**

> 当前阶段不接入 AI，也不处理电脑本地文件。工具只操作 Docker 映射到 `/media` 的 NAS 文件，优先把“扫描 → 整理 → NFO / 图片生成 → 绿联影视中心识别 → 长期维护”做稳定。

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

## v0.1.8：封面构图优化

v0.1.8 解决竖屏、4:3、超宽屏等视频直接抽帧后，在影视中心卡片中被二次裁切导致主体缺失的问题。

所有自动生成图片都采用“**固定目标比例 + 原画面完整保留 + 同帧模糊背景补齐**”策略：

```text
原始画面（不裁切）
        ↓
等比缩放到目标画布内
        ↓
同一帧放大铺满作为模糊背景
        ↓
背景轻微压暗 / 降饱和
        ↓
前景边缘透明羽化
        ↓
柔和融合，不出现突兀硬边
```

输出规格：

```text
poster.jpg       1000 × 1500   2:3
fanart.jpg       1920 × 1080   16:9
Episode JPG      1280 × 720    16:9
```

前景层始终使用等比 `fit`，不会为了填满画布而中心裁切；只有装饰性的模糊背景层允许裁切。上传的 poster / fanart 如果比例不匹配，也使用相同规则标准化。

## v0.1.7：轻量更新

v0.1.7 将“运行环境”和“应用代码”分离，减少国内网络环境下频繁拉取大型 Docker 镜像的问题。

### 普通版本更新

日常 Python / HTML / CSS / JS / NFO 逻辑变化，只下载：

```text
nas-media-manager-update-<version>.tar.gz
```

更新包只包含：

```text
app/
VERSION
```

不会重新下载 Python、FFmpeg 和系统依赖。

应用内进入：

```text
设置 → 检查更新 → 立即轻量更新
```

更新流程：

```text
GitHub Release
    ↓
读取 update-manifest.json
    ↓
检查 Runtime API
    ↓
下载轻量 tar.gz
    ↓
SHA256 + 路径安全校验
    ↓
安装到 /data/app_runtime/versions/<version>
    ↓
原子切换 current
    ↓
Runtime Launcher 自动重启 Uvicorn
```

旧版本保留在 `/data/app_runtime/versions/`，设置页可以一键回滚。

### Runtime 更新

只有这些内容变化时才需要重新拉 Docker：

- Python 基础镜像
- FFmpeg / 系统依赖
- `requirements.txt`
- `runtime/launcher.py`
- `RUNTIME_API`

当前 Runtime：

```text
ghcr.io/rosenray/nas-media-manager:runtime-1
```

详细说明见：[轻量更新机制](docs/LIGHTWEIGHT_UPDATES.md)。

## v0.1.6：移动端体验

360～430px Android 竖屏作为主要适配目标，同时保留桌面端宽屏体验：

- 固定底部导航：媒体 / 集合 / 任务 / 设置。
- 媒体文件与增量添加使用触控友好的文件卡片。
- 视频和可批量处理文件夹支持点击整行勾选。
- 文件选择操作栏固定在底部导航上方。
- 手机表单单列化，输入框和按钮扩大触控区域。
- 截图候选使用横向滑动。
- 长路径预览改为上下排列。
- 适配全面屏 `safe-area-inset-bottom`。

## 当前能力

### 文件扫描与整理

- 浏览 Docker 映射的 NAS 媒体目录。
- 读取大小、修改时间、时长、分辨率和编码信息。
- 当前目录“全选视频”与选择数量统计。
- 自动生成 Episode 编号。
- 新建集合年份默认当前年份；异常 1970 文件时间回退到当天。
- 编辑集合名称、简介、年份、Genre、单集标题、简介和日期。
- 支持“整理并生成媒资”与“仅生成媒资”。

### 批量文件夹生成集合

- 一次勾选多个文件夹，一个文件夹对应一个集合。
- 集合名称默认使用文件夹名。
- 只处理文件夹当前层视频，不递归合并子目录。
- 自动过滤空目录、无支持视频目录、已有 `tvshow.nfo` 的集合和疑似已整理目录。
- 执行前提供统一预览、过滤原因和冲突检查。
- 默认输出绿联兼容 `Season 01 + SxxExx` 结构。
- 批量任务支持失败回滚和成功后整体撤销。

### 本地媒资

- 生成 `tvshow.nfo`。
- 生成 Episode NFO。
- 按季模式支持 `season.nfo`。
- `poster.jpg` / `fanart.jpg` 支持上传或从视频截图。
- poster 自动标准化为 2:3；fanart 与 Episode 图片自动标准化为 16:9。
- 不裁切原始前景画面；比例差异区域使用同帧模糊背景和羽化边缘补齐。
- Episode 图片支持 FFmpeg 候选截图和自动补齐。

### 已整理集合维护

- 自动发现已整理集合。
- 查看 Episode、poster / fanart / NFO / JPG 完整性。
- 修改集合标题、简介、年份、Genre。
- 修改单集标题、简介和日期，不主动重命名已有视频。
- 向已有集合增量添加视频，从当前最大 Episode + 1 编号。
- 检查缺失 NFO/JPG、Episode 断号和重复编号。
- 支持补齐缺失 NFO 和单集 JPG。

### 安全机制

- 新集合、增量追加和批量文件夹处理执行前都有预览与冲突检测。
- 默认不覆盖已有视频、NFO 或图片。
- SQLite 保存草稿、任务和操作记录。
- 执行中发生异常时尝试自动回滚。
- 成功任务支持撤销。
- 轻量更新包执行 SHA256 和压缩包路径安全校验。
- 应用版本切换使用独立版本目录和原子 `current` 链接。

## 绿联兼容模式

家庭影像在界面中采用“无季集合”，底层保持绿联影视中心已实机验证更稳定的 TV Episode 结构：

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

详细说明见：[绿联影视中心兼容说明](docs/UGREEN_COMPATIBILITY.md)。

## 推荐部署

v0.1.7 及以上使用稳定 Runtime；从旧的完整镜像方式迁移时只需要完成一次 Runtime 部署：

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

首次迁移：

```bash
docker compose pull
docker compose up -d
```

访问：

```text
http://NAS-IP:18765
```

以后普通版本更新不再执行 `docker compose pull`，直接在 Web 设置页轻量更新即可。

绿联 NAS 部署见：[绿联 NAS Docker 部署](docs/DEPLOYMENT_UGREEN.md)。

## 发布流程

`main` 通过测试后：

```text
pytest
  ├─→ 生成轻量更新包 → GitHub Release
  └─→ 检测 Runtime 是否变化
          ├─ 无变化：不构建 Docker Runtime
          └─ 有变化：构建 amd64 + arm64 runtime-N
```

这样绝大多数后续版本只需要下载很小的应用代码包。

## 技术栈

- Python 3.12
- FastAPI
- Jinja2
- SQLite
- FFmpeg / ffprobe
- Docker / Docker Compose
- GitHub Actions / GitHub Releases / GitHub Container Registry

## 项目结构

```text
nas-media-manager/
├── app/
│   ├── core/
│   │   ├── media.py
│   │   ├── nfo.py
│   │   ├── organizer.py
│   │   ├── collections.py
│   │   ├── batch.py
│   │   ├── thumbnails.py
│   │   └── updater.py
│   ├── templates/
│   ├── static/
│   ├── main.py
│   ├── runtime_main.py
│   └── version.py
├── runtime/
│   └── launcher.py
├── docs/
│   ├── DEPLOYMENT_UGREEN.md
│   ├── LIGHTWEIGHT_UPDATES.md
│   ├── ROADMAP.md
│   └── UGREEN_COMPATIBILITY.md
├── tests/
├── Dockerfile
├── docker-compose.yml
├── RUNTIME_API
└── VERSION
```

## 测试

```bash
python -m pytest -q
```

Pull Request 和 `main` push 都会执行完整回归测试；只有测试通过后才发布轻量更新包和必要的 Runtime 镜像。

## 当前限制

- 仅处理 NAS Docker 映射目录，不读取电脑本地文件。
- 批量文件夹模式只扫描当前层视频，不递归子目录。
- 暂不接入 AI 大模型。
- 当前主要针对绿联影视中心验证。
- 不直接调用或修改绿联影视中心私有数据库。
- 轻量更新目前默认从 GitHub Release 下载；国内网络非常差时，后续可增加自定义镜像源。

## Roadmap

下一阶段优先考虑：

- PWA / 添加到 Android 主屏幕。
- 国内镜像 / 自定义更新源。
- 已整理集合的海报 / 背景重新截图与替换。
- 更高效的批量单集封面确认与重新截图。
- Episode 调序 / 插入后的安全重编号。
- 集合扫描缓存与大媒体库性能优化。

详细计划见：[Roadmap](docs/ROADMAP.md)。

## 版本记录

见：[CHANGELOG.md](CHANGELOG.md)。
