import os
import shutil
import subprocess
from pathlib import Path

TEST_ROOT = Path('/tmp/nmm-v013-tests')
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
MEDIA = TEST_ROOT / 'media'
DATA = TEST_ROOT / 'data'
MEDIA.mkdir(parents=True)
DATA.mkdir(parents=True)
os.environ['MEDIA_ROOT'] = str(MEDIA)
os.environ['DATA_ROOT'] = str(DATA)

from app.config import THUMB_ROOT, ensure_runtime_dirs
from app.core.media import MediaPathError, default_episode_title, resolve_media_path
from app.core.nfo import episode_nfo, tvshow_nfo
from app.core.organizer import execute_plan, preview_plan, undo_operations

ensure_runtime_dirs()


def make_payload():
    src_dir = MEDIA / '原始视频'
    src_dir.mkdir(exist_ok=True)
    (src_dir / '001.mp4').write_bytes(b'fake-video-one')
    (src_dir / '002.mp4').write_bytes(b'fake-video-two')
    return {
        'organization_mode': 'seasoned',
        'ugreen_compat': False,
        'auto_episode_thumbs': False,
        'series_title': '海南旅行',
        'series_plot': '家庭旅行记录',
        'year': '2026',
        'genres': '家庭,旅行',
        'season': 1,
        'season_title': '第一季',
        'output_parent': '',
        'poster_cache': '',
        'fanart_cache': '',
        'episodes': [
            {'source': '原始视频/001.mp4', 'episode': 1, 'title': '出发', 'plot': '准备出发', 'aired': '2026-07-01', 'selected_thumb': ''},
            {'source': '原始视频/002.mp4', 'episode': 2, 'title': '海边', 'plot': '到达海边', 'aired': '2026-07-02', 'selected_thumb': ''},
        ],
    }


def reset_media():
    for child in MEDIA.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def make_real_video(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10',
        '-t', '1.2', '-pix_fmt', 'yuv420p', str(path),
    ], check=True)


def test_path_cannot_escape_media_root():
    try:
        resolve_media_path('../outside')
        assert False, 'expected MediaPathError'
    except MediaPathError:
        pass


def test_nfo_contains_core_fields():
    show = tvshow_nfo(title='海南旅行', plot='简介', year='2026', genres=['家庭', '旅行'])
    ep = episode_nfo(title='出发', showtitle='海南旅行', season=1, episode=1, plot='简介', aired='2026-07-01')
    assert '<title>海南旅行</title>' in show
    assert '<genre>旅行</genre>' in show
    assert '<season>1</season>' in ep
    assert '<episode>1</episode>' in ep
    assert '<aired>2026-07-01</aired>' in ep


def test_hash_filename_gets_human_default_title():
    assert default_episode_title('1d2ee3861f3079066abc7624d0a486e7.mp4', 1) == '第1集'
    assert default_episode_title('公园玩耍.mp4', 2) == '公园玩耍'


def test_execute_and_undo_roundtrip():
    reset_media()
    payload = make_payload()
    preview = preview_plan(payload, 'draft1')
    assert not preview['conflicts']
    assert preview['moves'][0]['target'].endswith('海南旅行 - S01E01 - 出发.mp4')

    ops = execute_plan(payload, 'draft1')
    target = MEDIA / '海南旅行' / 'Season 01' / '海南旅行 - S01E01 - 出发.mp4'
    assert target.exists()
    assert (MEDIA / '海南旅行' / 'tvshow.nfo').exists()
    assert (MEDIA / '海南旅行' / 'Season 01' / '海南旅行 - S01E02 - 海边.nfo').exists()
    assert not (MEDIA / '原始视频' / '001.mp4').exists()

    errors = undo_operations(ops)
    assert errors == []
    assert (MEDIA / '原始视频' / '001.mp4').exists()
    assert (MEDIA / '原始视频' / '002.mp4').exists()
    assert not target.exists()


def test_conflict_is_reported():
    reset_media()
    payload = make_payload()
    conflict = MEDIA / '海南旅行' / 'Season 01'
    conflict.mkdir(parents=True)
    (conflict / '海南旅行 - S01E01 - 出发.mp4').write_bytes(b'existing')
    preview = preview_plan(payload, 'draft2')
    assert preview['conflicts']
    assert any('目标视频已存在' in item for item in preview['conflicts'])


def test_metadata_only_keeps_video_in_place():
    reset_media()
    series_dir = MEDIA / '成长记录'
    season_dir = series_dir / 'Season 01'
    season_dir.mkdir(parents=True)
    video = season_dir / 'S01E01 - 公园.mp4'
    video.write_bytes(b'video')
    payload = {
        'mode': 'metadata_only',
        'organization_mode': 'seasoned',
        'ugreen_compat': False,
        'auto_episode_thumbs': False,
        'series_title': '成长记录',
        'series_plot': '测试',
        'year': '2026',
        'genres': '家庭影像',
        'season': 1,
        'season_title': 'Season 01',
        'output_parent': '',
        'poster_cache': '',
        'fanart_cache': '',
        'episodes': [
            {'source': '成长记录/Season 01/S01E01 - 公园.mp4', 'episode': 1, 'title': '公园', 'plot': '', 'aired': '', 'selected_thumb': ''},
        ],
    }
    preview = preview_plan(payload, 'draft-meta')
    assert preview['mode'] == 'metadata_only'
    assert preview['moves'] == []
    ops = execute_plan(payload, 'draft-meta')
    assert video.exists()
    assert video.with_suffix('.nfo').exists()
    assert (series_dir / 'tvshow.nfo').exists()
    errors = undo_operations(ops)
    assert errors == []
    assert video.exists()
    assert not video.with_suffix('.nfo').exists()


def test_old_flat_collection_preserves_v012_root_layout():
    reset_media()
    payload = make_payload()
    payload['organization_mode'] = 'flat'
    payload['ugreen_compat'] = False
    preview = preview_plan(payload, 'draft-flat-old')
    assert preview['collection_dir'] == '海南旅行'
    assert preview['moves'][0]['target'].endswith('海南旅行/海南旅行 - S01E01 - 出发.mp4')
    assert not any(g['path'].endswith('/season.nfo') for g in preview['generated'])


def test_ugreen_flat_collection_uses_hidden_season_dir_and_scraper_safe_names():
    reset_media()
    payload = make_payload()
    payload['organization_mode'] = 'flat'
    payload['ugreen_compat'] = True
    payload['season'] = 8
    preview = preview_plan(payload, 'draft-ugreen')
    assert preview['organization_mode'] == 'flat'
    assert preview['ugreen_compat'] is True
    assert preview['flat_uses_season_dir'] is True
    assert preview['season'] == 1
    assert preview['collection_dir'] == '海南旅行/Season 01'
    assert preview['moves'][0]['target'].endswith('海南旅行/Season 01/海南旅行 - S01E01.mp4')
    assert preview['moves'][1]['target'].endswith('海南旅行/Season 01/海南旅行 - S01E02.mp4')
    assert not any(g['path'].endswith('/season.nfo') for g in preview['generated'])

    ops = execute_plan(payload, 'draft-ugreen')
    root = MEDIA / '海南旅行'
    assert (root / 'Season 01' / '海南旅行 - S01E01.mp4').exists()
    ep_nfo = (root / 'Season 01' / '海南旅行 - S01E01.nfo').read_text(encoding='utf-8')
    assert '<title>出发</title>' in ep_nfo
    assert '<showtitle>海南旅行</showtitle>' in ep_nfo
    assert '<season>1</season>' in ep_nfo
    assert undo_operations(ops) == []


def test_artwork_candidate_can_be_used_as_poster_and_fanart():
    reset_media()
    payload = make_payload()
    payload['organization_mode'] = 'flat'
    payload['ugreen_compat'] = True
    for kind in ('poster', 'fanart'):
        folder = THUMB_ROOT / 'art-draft' / 'artwork' / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'candidate_01.jpg').write_bytes((kind + '-image').encode())
        payload[f'selected_{kind}_thumb'] = 'candidate_01.jpg'
    preview = preview_plan(payload, 'art-draft')
    paths = {g['path'] for g in preview['generated']}
    assert '海南旅行/poster.jpg' in paths
    assert '海南旅行/fanart.jpg' in paths
    ops = execute_plan(payload, 'art-draft')
    assert (MEDIA / '海南旅行' / 'poster.jpg').read_bytes() == b'poster-image'
    assert (MEDIA / '海南旅行' / 'fanart.jpg').read_bytes() == b'fanart-image'
    assert undo_operations(ops) == []


def test_auto_episode_thumbnail_uses_real_video_and_can_undo():
    reset_media()
    source = MEDIA / '原始视频' / 'opaquehash.mp4'
    make_real_video(source)
    payload = {
        'mode': 'organize',
        'organization_mode': 'flat',
        'ugreen_compat': True,
        'auto_episode_thumbs': True,
        'series_title': '家庭相册',
        'series_plot': '',
        'year': '',
        'genres': '家庭影像',
        'season': 1,
        'season_title': 'Season 01',
        'output_parent': '',
        'poster_cache': '',
        'fanart_cache': '',
        'episodes': [
            {'source': '原始视频/opaquehash.mp4', 'episode': 1, 'title': '第1集', 'plot': '', 'aired': '', 'selected_thumb': ''},
        ],
    }
    preview = preview_plan(payload, 'auto-thumb')
    assert any(x['kind'] == 'auto_thumb' and x['path'].endswith('家庭相册 - S01E01.jpg') for x in preview['generated'])
    ops = execute_plan(payload, 'auto-thumb')
    thumb = MEDIA / '家庭相册' / 'Season 01' / '家庭相册 - S01E01.jpg'
    assert thumb.exists() and thumb.stat().st_size > 0
    assert undo_operations(ops) == []
    assert source.exists()


def make_ugreen_collection(name='家庭相册', episodes=(1, 2)):
    from app.core.nfo import episode_nfo, tvshow_nfo
    root = MEDIA / name
    season = root / 'Season 01'
    season.mkdir(parents=True, exist_ok=True)
    (root / 'tvshow.nfo').write_text(tvshow_nfo(title=name, plot='原简介', year='2026', genres=['家庭影像']), encoding='utf-8')
    for no in episodes:
        video = season / f'{name} - S01E{no:02d}.mp4'
        video.write_bytes(f'video-{no}'.encode())
        video.with_suffix('.nfo').write_text(episode_nfo(title=f'第{no}集', showtitle=name, season=1, episode=no, plot='', aired=''), encoding='utf-8')
    return root


def test_collection_discovery_and_integrity_check():
    reset_media()
    root = make_ugreen_collection(episodes=(1, 3))
    (root / 'poster.jpg').write_bytes(b'poster')
    from app.core.collections import list_collections, load_collection
    items = list_collections()
    assert len(items) == 1
    item = load_collection('家庭相册')
    assert item['episode_count'] == 2
    codes = {x['code'] for x in item['issues']}
    assert 'missing_fanart' in codes
    assert 'missing_episode_thumb' in codes
    assert 'episode_gap' in codes


def test_collection_metadata_update_can_undo():
    reset_media()
    make_ugreen_collection(episodes=(1,))
    from app.core.collections import update_collection_metadata
    ops = update_collection_metadata('家庭相册', title='家庭影像集', plot='新简介', year='2027', genres='家庭,旅行')
    show = (MEDIA / '家庭相册' / 'tvshow.nfo').read_text(encoding='utf-8')
    ep = (MEDIA / '家庭相册' / 'Season 01' / '家庭相册 - S01E01.nfo').read_text(encoding='utf-8')
    assert '<title>家庭影像集</title>' in show
    assert '<showtitle>家庭影像集</showtitle>' in ep
    assert undo_operations(ops) == []
    restored = (MEDIA / '家庭相册' / 'tvshow.nfo').read_text(encoding='utf-8')
    assert '<title>家庭相册</title>' in restored


def test_episode_metadata_update_does_not_rename_video():
    reset_media()
    make_ugreen_collection(episodes=(1,))
    from app.core.collections import update_episode_metadata
    video_rel = '家庭相册/Season 01/家庭相册 - S01E01.mp4'
    ops = update_episode_metadata('家庭相册', video_rel, title='公园玩耍', plot='下午去公园', aired='2026-08-17')
    assert (MEDIA / video_rel).exists()
    nfo = (MEDIA / '家庭相册' / 'Season 01' / '家庭相册 - S01E01.nfo').read_text(encoding='utf-8')
    assert '<title>公园玩耍</title>' in nfo
    assert '<aired>2026-08-17</aired>' in nfo
    assert undo_operations(ops) == []


def test_append_preview_starts_after_current_max_and_keeps_existing():
    reset_media()
    make_ugreen_collection(episodes=(1, 2, 3))
    source_dir = MEDIA / '待追加'
    source_dir.mkdir()
    (source_dir / 'new-a.mp4').write_bytes(b'a')
    (source_dir / 'new-b.mp4').write_bytes(b'b')
    from app.core.collections import build_append_payload, preview_append, execute_append
    payload = build_append_payload('家庭相册', ['待追加/new-a.mp4', '待追加/new-b.mp4'])
    payload['auto_episode_thumbs'] = False
    assert [x['episode'] for x in payload['episodes']] == [4, 5]
    plan = preview_append(payload)
    assert not plan['conflicts']
    assert plan['items'][0]['target'].endswith('家庭相册 - S01E04.mp4')
    ops = execute_append(payload)
    assert (MEDIA / '家庭相册' / 'Season 01' / '家庭相册 - S01E01.mp4').exists()
    assert (MEDIA / '家庭相册' / 'Season 01' / '家庭相册 - S01E04.mp4').exists()
    assert (MEDIA / '家庭相册' / 'Season 01' / '家庭相册 - S01E05.nfo').exists()
    assert undo_operations(ops) == []
    assert (source_dir / 'new-a.mp4').exists()
    assert (source_dir / 'new-b.mp4').exists()


def test_append_keeps_existing_filename_prefix_after_display_title_change():
    reset_media()
    make_ugreen_collection(episodes=(1,))
    from app.core.collections import update_collection_metadata, build_append_payload, preview_append
    update_collection_metadata('家庭相册', title='新的展示标题', plot='', year='', genres='家庭影像')
    src = MEDIA / '新增'
    src.mkdir()
    (src / 'a.mp4').write_bytes(b'a')
    payload = build_append_payload('家庭相册', ['新增/a.mp4'])
    payload['auto_episode_thumbs'] = False
    plan = preview_append(payload)
    assert plan['items'][0]['target'].endswith('家庭相册 - S01E02.mp4')
    assert plan['collection']['title'] == '新的展示标题'
