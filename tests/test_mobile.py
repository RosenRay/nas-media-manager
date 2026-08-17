from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mobile_navigation_and_safe_area_are_enabled():
    base = read("app/templates/base.html")
    css = read("app/static/mobile.css")
    assert 'viewport-fit=cover' in base
    assert 'mobile-bottom-nav' in base
    assert 'safe-area-inset-bottom' in css


def test_media_browser_uses_touch_card_contract():
    browse = read("app/templates/browse.html")
    css = read("app/static/mobile.css")
    assert 'mobile-media-table' in browse
    assert 'selectable-row' in browse
    assert 'mobile-file-toolbar' in browse
    assert '.mobile-media-table tr.selectable-row.selected' in css


def test_append_browser_has_no_redundant_clear_selection_button():
    append = read("app/templates/collection_add.html")
    assert '全选视频' in append
    assert '取消全选' not in append
    assert 'mobile-media-table' in append


def test_mobile_thumbnails_are_horizontal_scroll_strip():
    css = read("app/static/mobile.css")
    assert 'scroll-snap-type:x mandatory' in css
    assert '.thumb-card{flex:0 0 min(76vw,280px)' in css


def test_batch_preview_has_mobile_labels():
    preview = read("app/templates/batch_preview.html")
    assert 'mobile-preview-table' in preview
    assert 'data-label="源文件夹"' in preview
    assert 'data-label="目标目录"' in preview
