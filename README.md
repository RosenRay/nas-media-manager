# NAS Media Manager

面向 NAS 私人视频的本地媒体整理与 NFO 元数据管理工具。

当前版本：**v0.1.4**  
当前重点：**绿联 NAS / UGOS Pro + 影视中心兼容输出**

> 当前阶段不接入 AI，也不处理电脑本地文件。工具只操作 Docker 映射到 `/media` 的 NAS 文件，优先把“扫描 → 整理 → NFO / 图片生成 → 绿联影视中心识别”这条基础链路做稳定。

## 适合什么场景

传统影视刮削器擅长电影和电视剧，但家庭录像、旅行 Vlog、课程、自己拍摄的视频通常没有 TMDB 等在线元数据。

NAS Media Manager 用于把这些内容整理成媒体中心更容易读取的本地媒资结构：

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
- 扫描常见视频格式。
- 读取大小、修改时间、时长、分辨率和编码信息。
- 当前目录视频全选 / 取消全选 / 已选数量。
- 自动生成 Episode 编号。
- 支持人工编辑集合名称、简介、年份、Genre、单集标题、简介和日期。
- 支持“整理并生成媒资”与“仅生成媒资”。

### 本地媒资

- 生成 `tvshow.nfo`。
- 生成 Episode NFO。
- 按季模式支持 `season.nfo`。
- `poster.jpg`：上传图片或从集合内指定视频截取候选画面。
- `fanart.jpg`：上传图片或从集合内指定视频截取候选画面。
- 单集图片：FFmpeg 生成候选帧并选择。
- 可自动补齐未手工选择的单集封面。

### 已整理集合维护

- 自动发现已整理集合并进入详情页维护。
- 查看 Episode 列表以及 poster / fanart / NFO / 单集图片完整性。
- 修改集合标题、简介、年份、Genre，并同步已有 Episode NFO 的 `showtitle`。
- 修改单集标题、简介和日期，只更新 NFO，不主动重命名视频。
- 向已有集合增量添加新视频，从当前最大 Episode + 1 自动编号。
- 检查缺失 NFO、缺失单集图片、Episode 断号与重复编号。
- 可补齐缺失 NFO，并为缺失单集 JPG 自动截取默认画面。

### 安全机制

- 新集合整理与增量追加执行前提供预览和冲突检测。
- 检测目标文件冲突。
- 默认不覆盖已有视频、NFO 或图片。
- SQLite 保存草稿、任务和操作记录。
- 执行中发生异常时尝试自动回滚。
- 成功任务支持撤销；删除生成文件前会校验文件是否被修改。

## 绿联兼容模式

家庭影像在界面中采用“无季集合”的概念，但为了兼容绿联影视中心的 Episode 扫描，当前版本继续采用下面的底层结构：

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

`Season 01` 只是底层兼容目录，家庭影像用户不需要维护“季”。

这一结构已在绿联 NAS 影视中心实机验证，可将同一集合中的 Episode 正确归组。

详细说明见：[绿联影视中心兼容说明](docs/UGREEN_COMPATIBILITY.md)。

## 技术栈

为了降低部署和维护成本，当前版本保持单体 Web 应用：

- Python 3.12
- FastAPI
- Jinja2
- SQLite
- FFmpeg / ffprobe
- Docker / Docker Compose

暂未引入 Vue、Redis、PostgreSQL、消息队列或 AI 服务。

## 快速部署

### 1. 修改 `docker-compose.yml`

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

只需要把左侧：

```text
/你的NAS真实视频目录
```

替换成 NAS 上真实存在的视频目录。右侧 `/media` 与 `/data` 保持不变。

### 2. 构建启动

```bash
docker compose up -d --build
```

### 3. 访问

```text
http://NAS-IP:18765
```

健康检查：

```text
http://NAS-IP:18765/health
```

绿联 NAS 的完整操作步骤见：[绿联 NAS Docker 部署](docs/DEPLOYMENT_UGREEN.md)。

## 项目结构

```text
nas-media-manager/
├── app/
│   ├── core/
│   │   ├── media.py          # 媒体扫描、路径与命名处理
│   │   ├── nfo.py            # NFO 生成
│   │   ├── organizer.py      # 整理计划、执行、回滚与绿联兼容规则
│   │   ├── collections.py    # 已整理集合扫描、维护、完整性与增量追加
│   │   └── thumbnails.py     # FFmpeg 截图与图片处理
│   ├── static/
│   ├── templates/
│   ├── config.py
│   ├── db.py
│   └── main.py               # FastAPI Web 入口
├── docs/
│   ├── DEPLOYMENT_UGREEN.md
│   ├── ROADMAP.md
│   └── UGREEN_COMPATIBILITY.md
├── tests/
│   └── test_core.py
├── CHANGELOG.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── VERSION
```

## 测试

```bash
python -m pytest -q
```

当前版本 `v0.1.4`：

```text
15 passed
```

## 使用建议

程序需要对媒体目录进行写操作。正式处理重要视频前，建议先复制 2～3 个测试视频验证：

```text
扫描
→ 编辑
→ 截图
→ 预览
→ 执行
→ 绿联影视中心重新扫描
→ 确认集合归组
→ 测试撤销
```

确认环境和绿联影视中心行为符合预期后，再扩大 `/media` 映射范围。

## 当前限制

- 仅处理 NAS Docker 映射目录，不读取电脑本地文件。
- 暂不接入 AI 大模型。
- 当前主要针对绿联影视中心验证，其他媒体平台尚未建立专门适配层。
- 不直接调用或修改绿联影视中心私有数据库。

## Roadmap

`v0.1.4` 已完成第一阶段集合维护闭环。下一阶段继续优先优化日常使用效率：

- 已整理集合的海报 / 背景重新截图与替换。
- 更高效的批量单集封面确认与重新截图。
- Episode 调序 / 插入后的安全重编号方案。
- 集合扫描缓存与大媒体库性能优化。

后续再考虑电脑本地文件、多媒体源、Jellyfin / Emby / Kodi 适配，以及可选 AI 能力。

详细计划见：[Roadmap](docs/ROADMAP.md)。

## 版本记录

见：[CHANGELOG.md](CHANGELOG.md)。

## 截图

项目刚完成首个可用版本归档，界面截图将在后续版本补充。
