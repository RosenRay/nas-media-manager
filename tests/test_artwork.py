import os
import subprocess
from pathlib import Path

# Keep the same process-wide roots used by the existing test suite.
os.environ['MEDIA_ROOT'] = '/tmp/nmm-v013-tests/media'
os.environ['DATA_ROOT'] = '/tmp/nmm-v013-tests/data'

from app.core.thumbnails import (
    _composition_filter,
    _render_artwork,
    artwork_spec,
    extract_default_thumbnail,
)


def make_video(path: Path, size: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=10',
        '-t', '1.2', '-pix_fmt', 'yuv420p', str(path),
    ], check=True)


def image_size(path: Path) -> tuple[int, int]:
    proc = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', str(path),
    ], capture_output=True, text=True, check=True)
    width, height = proc.stdout.strip().split('x')
    return int(width), int(height)


def test_artwork_specs_match_media_center_shapes():
    assert artwork_spec('poster') == (1000, 1500)
    assert artwork_spec('fanart') == (1920, 1080)
    assert artwork_spec('episode') == (1280, 720)


def test_filter_keeps_foreground_full_and_feathers_only_padded_axes():
    value = _composition_filter('episode')
    # The decorative background may crop to fill, but the actual foreground
    # must always shrink-to-fit and keep the complete source frame.
    assert 'force_original_aspect_ratio=increase' in value
    assert 'force_original_aspect_ratio=decrease' in value
    assert 'gblur=' in value
    assert "geq=r='r(X,Y)'" in value
    # X/Y feathering is conditional on the scaled foreground actually being
    # narrower/shorter than the target. Native 16:9 therefore stays opaque.
    assert 'if(lt(W,1278)' in value
    assert 'if(lt(H,718)' in value
    assert "a='255*min(" in value


def test_portrait_episode_thumbnail_is_fixed_16_9_without_source_crop(tmp_path):
    source = tmp_path / 'portrait.mp4'
    target = tmp_path / 'episode.jpg'
    make_video(source, '360x640')
    extract_default_thumbnail(source, target)
    assert target.exists() and target.stat().st_size > 0
    assert image_size(target) == (1280, 720)


def test_ultrawide_episode_thumbnail_is_fixed_16_9_without_source_crop(tmp_path):
    source = tmp_path / 'wide.mp4'
    target = tmp_path / 'episode.jpg'
    make_video(source, '640x240')
    extract_default_thumbnail(source, target)
    assert image_size(target) == (1280, 720)


def test_native_16_9_episode_thumbnail_is_fixed_16_9(tmp_path):
    source = tmp_path / 'native.mp4'
    target = tmp_path / 'episode.jpg'
    make_video(source, '640x360')
    extract_default_thumbnail(source, target)
    assert image_size(target) == (1280, 720)


def test_poster_and_fanart_use_their_own_target_ratios(tmp_path):
    source = tmp_path / 'portrait.mp4'
    make_video(source, '360x640')
    poster = tmp_path / 'poster.jpg'
    fanart = tmp_path / 'fanart.jpg'
    _render_artwork(source, poster, 'poster', at=0.5)
    _render_artwork(source, fanart, 'fanart', at=0.5)
    assert image_size(poster) == (1000, 1500)
    assert image_size(fanart) == (1920, 1080)
