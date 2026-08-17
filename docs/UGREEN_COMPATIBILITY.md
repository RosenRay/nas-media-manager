# 绿联影视中心兼容说明

本文记录 NAS Media Manager `v0.1.3` 当前经过实机验证的绿联影视中心输出策略。

> 目标不是修改绿联影视中心内部数据库，而是生成本地 NFO 和图片，让影视中心通过正常扫描读取。

## 家庭影像模式

家庭录像、旅行、Vlog 等内容在产品界面中采用“无季视频集合”的概念，用户不需要理解或维护 Season。

为了兼容绿联影视中心的 TV/Episode 扫描逻辑，磁盘上仍默认输出：

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

### 设计原则

- `Season 01` 只是底层兼容目录，不作为家庭影像的用户概念。
- Episode NFO 仍保留 `season=1` 和正确的 episode 编号。
- 家庭影像兼容模式当前不生成 `season.nfo`。
- 文件名只保留集合名和 `SxxExx`，实际单集标题写入 NFO。
- 这样可以减少随机 Hash、原始文件名或额外标题对扫描归组造成干扰。

## NFO 示例

### tvshow.nfo

```xml
<?xml version="1.0" encoding="utf-8"?>
<tvshow>
  <title>家庭影像集合</title>
  <plot>家庭影像说明</plot>
  <year>2026</year>
  <genre>家庭</genre>
</tvshow>
```

### Episode NFO

```xml
<?xml version="1.0" encoding="utf-8"?>
<episodedetails>
  <title>第1集</title>
  <showtitle>家庭影像集合</showtitle>
  <season>1</season>
  <episode>1</episode>
  <plot>单集说明</plot>
</episodedetails>
```

## 图片

集合级：

- `poster.jpg`：集合总海报。
- `fanart.jpg`：集合背景图。

单集级：

- 与视频/NFO 同名的 `.jpg` 作为单集图片。
- 可以手工选择候选截图，也可以开启自动补齐。

## 当前实测结论

早期完全取消 `Season 01` 物理目录时，绿联影视中心曾出现部分 Episode 被拆分成独立集合的情况。

`v0.1.3` 改为“界面无季、底层 Season 01 兼容目录 + 简化 Episode 文件名”后，已在绿联 NAS 影视中心实机验证：同一集合 Episode 可以正确归组识别。

不同 UGOS / 影视中心版本仍可能存在差异，因此在扩大到正式媒体库前，建议先使用少量复制的视频验证。
