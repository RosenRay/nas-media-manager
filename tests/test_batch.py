from datetime import datetime
import os
from pathlib import Path

import app.core.media as media
from app.core.batch import build_batch_payload, build_folder_collection_payload, execute_batch_payload
from app.core.organizer import undo_operations


def use_root(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / 'media'
    root.mkdir()
    monkeypatch.setattr(media, 'MEDIA_ROOT', root)
    monkeypatch.setattr(media, 'probe_video', lambda path, timeout=8: {
        'duration': None, 'width': None, 'height': None, 'codec': None,
    })
    return root


def test_default_draft_uses_current_year_and_avoids_1970(monkeypatch, tmp_path):
    root = use_root(monkeypatch, tmp_path)
    folder = root / '家庭录像'
    folder.mkdir()
    video = folder / '001.mp4'
    video.write_bytes(b'video')
    os.utime(video, (0, 0))

    payload = media.default_draft(['家庭录像/001.mp4'])
    assert payload['year'] == str(datetime.now().year)
    assert payload['episodes'][0]['aired'].startswith(str(datetime.now().year))
    assert not payload['episodes'][0]['aired'].startswith('1970')


def test_scan_directory_marks_batch_eligible_and_filters(monkeypatch, tmp_path):
    root = use_root(monkeypatch, tmp_path)
    valid = root / '旅行'
    valid.mkdir()
    (valid / 'a.mp4').write_bytes(b'a')
    empty = root / '空目录'
    empty.mkdir()
    docs = root / '只有文档'
    docs.mkdir()
    (docs / 'readme.txt').write_text('x')
    managed = root / '已整理'
    managed.mkdir()
    (managed / 'tvshow.nfo').write_text('<tvshow/>')
    (managed / 'a.mp4').write_bytes(b'a')

    data = media.scan_directory('')
    items = {item['name']: item for item in data['entries']}
    assert items['旅行']['batch_eligible'] is True
    assert items['旅行']['batch_video_count'] == 1
    assert items['空目录']['batch_eligible'] is False
    assert items['空目录']['batch_skip_reason'] == '无视频'
    assert items['只有文档']['batch_eligible'] is False
    assert items['已整理']['batch_eligible'] is False
    assert items['已整理']['batch_skip_reason'] == '已整理集合'


def test_batch_folder_uses_folder_name_and_only_direct_videos(monkeypatch, tmp_path):
    root = use_root(monkeypatch, tmp_path)
    folder = root / '图图成长记录'
    folder.mkdir()
    (folder / 'b.mp4').write_bytes(b'b')
    (folder / 'a.mp4').write_bytes(b'a')
    nested = folder / '子目录'
    nested.mkdir()
    (nested / 'nested.mp4').write_bytes(b'nested')

    payload = build_folder_collection_payload('图图成长记录')
    assert payload['series_title'] == '图图成长记录'
    assert payload['year'] == str(datetime.now().year)
    assert len(payload['episodes']) == 2
    assert all('/子目录/' not in ep['source'] for ep in payload['episodes'])
    assert payload['organization_mode'] == 'flat'
    assert payload['ugreen_compat'] is True


def test_batch_payload_skips_empty_and_existing_collection(monkeypatch, tmp_path):
    root = use_root(monkeypatch, tmp_path)
    valid = root / '可处理'
    valid.mkdir()
    (valid / 'a.mp4').write_bytes(b'a')
    empty = root / '空目录'
    empty.mkdir()
    managed = root / '已整理'
    managed.mkdir()
    (managed / 'tvshow.nfo').write_text('<tvshow/>')
    (managed / 'a.mp4').write_bytes(b'a')

    payload = build_batch_payload(['可处理', '空目录', '已整理'])
    assert len(payload['items']) == 1
    assert payload['items'][0]['series_title'] == '可处理'
    assert len(payload['skipped']) == 2
    reasons = {item['name']: item['reason'] for item in payload['skipped']}
    assert reasons['空目录'] == '无视频'
    assert reasons['已整理'] == '已整理集合'


def test_batch_execute_and_undo_roundtrip(monkeypatch, tmp_path):
    root = use_root(monkeypatch, tmp_path)
    for name in ('集合A', '集合B'):
        folder = root / name
        folder.mkdir()
        (folder / '01.mp4').write_bytes((name + '-1').encode())
        (folder / '02.mp4').write_bytes((name + '-2').encode())

    payload = build_batch_payload(['集合A', '集合B'])
    for item in payload['items']:
        item['payload']['auto_episode_thumbs'] = False
    ops = execute_batch_payload(payload, 'batch-test')

    for name in ('集合A', '集合B'):
        assert (root / name / 'tvshow.nfo').exists()
        assert (root / name / 'Season 01' / f'{name} - S01E01.mp4').exists()
        assert (root / name / 'Season 01' / f'{name} - S01E02.nfo').exists()

    assert undo_operations(ops) == []
    for name in ('集合A', '集合B'):
        assert (root / name / '01.mp4').exists()
        assert (root / name / '02.mp4').exists()
