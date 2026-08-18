from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import THUMB_ROOT, UPLOAD_ROOT
from .media import probe_video, resolve_media_path


# Final local-artwork canvas sizes. The source frame itself is never cropped:
# it is scaled down to fit the canvas, while a blurred copy of the same frame
# fills the remaining area behind it.
ARTWORK_SPECS: dict[str, tuple[int, int]] = {
    "poster": (1000, 1500),
    "fanart": (1920, 1080),
    "episode": (1280, 720),
}

# Internal blend presets. v0.1.9 intentionally defaults to the stronger profile
# after real-media review showed that the previous narrow feather still left a
# visible rectangular foreground boundary on portrait material.
BLEND_PROFILES: dict[str, dict[str, float]] = {
    "standard": {
        "feather_ratio": 0.05,
        "blur_ratio": 0.045,
        "fade_power": 1.0,
        "brightness": -0.08,
        "saturation": 0.88,
    },
    "soft": {
        "feather_ratio": 0.09,
        "blur_ratio": 0.055,
        "fade_power": 1.18,
        "brightness": -0.10,
        "saturation": 0.83,
    },
    "strong": {
        "feather_ratio": 0.14,
        "blur_ratio": 0.065,
        "fade_power": 1.35,
        "brightness": -0.12,
        "saturation": 0.78,
    },
}
DEFAULT_BLEND_PROFILE = "strong"


def artwork_spec(kind: str) -> tuple[int, int]:
    try:
        return ARTWORK_SPECS[kind]
    except KeyError as exc:
        raise ValueError("不支持的图片类型") from exc


def _blend_profile(name: str) -> dict[str, float]:
    try:
        return BLEND_PROFILES[name]
    except KeyError as exc:
        raise ValueError("不支持的融合强度") from exc


def _composition_filter(kind: str, blend_profile: str = DEFAULT_BLEND_PROFILE) -> str:
    """Build a no-crop artwork filter with a broad, soft foreground blend.

    Background layer:
      - fills the target canvas by cropping only the decorative blurred copy;
      - is strongly blurred, darkened and desaturated so it does not compete
        with the complete foreground frame.

    Foreground layer:
      - uses force_original_aspect_ratio=decrease, so the source frame remains
        fully visible for portrait, 4:3, 16:9 and ultrawide videos;
      - feathers only edges next to an actually padded axis;
      - uses a wider, curved alpha transition so the foreground blends into the
        same-frame background instead of looking like a hard rectangle.
    """
    width, height = artwork_spec(kind)
    profile = _blend_profile(blend_profile)
    shortest = min(width, height)
    blur_sigma = max(18, round(shortest * profile["blur_ratio"]))
    feather = max(18, round(shortest * profile["feather_ratio"]))
    fade_power = profile["fade_power"]

    # Allow a 1px scale-rounding tolerance so native-ratio artwork does not get
    # an unnecessary blurred rim. W/H here are the scaled foreground dimensions.
    # pow(..., >1) keeps more of the broad transition semi-transparent, which
    # visually removes the old hard edge without cropping the source frame.
    x_fade = (
        f"if(lt(W,{width - 2}),"
        f"pow(max(0,min(1,min(X/{feather},(W-1-X)/{feather}))),{fade_power}),1)"
    )
    y_fade = (
        f"if(lt(H,{height - 2}),"
        f"pow(max(0,min(1,min(Y/{feather},(H-1-Y)/{feather}))),{fade_power}),1)"
    )
    alpha = f"255*min({x_fade},{y_fade})"

    return (
        "[0:v]split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},gblur=sigma={blur_sigma}:steps=2,"
        f"eq=brightness={profile['brightness']}:saturation={profile['saturation']}[bg];"
        f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        "format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[out]"
    )


def _render_artwork(
    source: Path,
    target: Path,
    kind: str,
    *,
    at: float | None = None,
    blend_profile: str = DEFAULT_BLEND_PROFILE,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if at is not None:
        command += ["-ss", f"{at:.3f}"]
    command += [
        "-i", str(source),
        "-frames:v", "1",
        "-filter_complex", _composition_filter(kind, blend_profile),
        "-map", "[out]",
        "-q:v", "2",
        str(target),
    ]
    subprocess.run(command, check=True, timeout=45)
    return target


def _extract_candidates(source_rel: str, target_dir: Path, kind: str, count: int = 5) -> list[Path]:
    source = resolve_media_path(source_rel)
    meta = probe_video(source)
    duration = float(meta.get("duration") or 0)
    if duration <= 0:
        raise ValueError("无法读取视频时长，不能生成候选缩略图")

    target_dir.mkdir(parents=True, exist_ok=True)
    for old in target_dir.glob("candidate_*.jpg"):
        old.unlink(missing_ok=True)

    ratios = [0.10, 0.30, 0.50, 0.70, 0.90]
    if count != 5:
        ratios = [(i + 1) / (count + 1) for i in range(count)]

    outputs: list[Path] = []
    for idx, ratio in enumerate(ratios, start=1):
        at = max(0.1, min(duration - 0.1, duration * ratio))
        out = target_dir / f"candidate_{idx:02d}.jpg"
        _render_artwork(source, out, kind, at=at)
        outputs.append(out)
    return outputs


def generate_candidates(draft_id: str, episode_index: int, source_rel: str, count: int = 5) -> list[Path]:
    return _extract_candidates(
        source_rel,
        THUMB_ROOT / draft_id / "episodes" / str(episode_index),
        "episode",
        count,
    )


def generate_artwork_candidates(draft_id: str, kind: str, source_rel: str, count: int = 5) -> list[Path]:
    if kind not in {"poster", "fanart"}:
        raise ValueError("不支持的图片类型")
    return _extract_candidates(source_rel, THUMB_ROOT / draft_id / "artwork" / kind, kind, count)


def save_uploaded_artwork(draft_id: str, kind: str, filename: str, content: bytes) -> str:
    if kind not in {"poster", "fanart"}:
        raise ValueError("不支持的图片类型")
    target_dir = UPLOAD_ROOT / draft_id
    target_dir.mkdir(parents=True, exist_ok=True)
    temp = target_dir / f".{kind}_upload{Path(filename or '').suffix.lower() or '.img'}"
    temp.write_bytes(content)
    output = target_dir / f"{kind}.jpg"
    try:
        # Manual artwork is user-authored content. Keep its composition intact
        # and only normalize the file format instead of applying auto framing.
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(temp), "-frames:v", "1", "-q:v", "2", str(output),
            ],
            check=True,
            timeout=20,
        )
    finally:
        temp.unlink(missing_ok=True)
    return str(output)


def _safe_cache_path(base: Path, filename: str) -> Path:
    base = base.resolve()
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("非法缓存图片路径") from exc
    return candidate


def thumb_cache_path(draft_id: str, episode_index: int, filename: str) -> Path:
    return _safe_cache_path(THUMB_ROOT / draft_id / "episodes" / str(episode_index), filename)


def artwork_cache_path(draft_id: str, kind: str, filename: str) -> Path:
    if kind not in {"poster", "fanart"}:
        raise ValueError("不支持的图片类型")
    return _safe_cache_path(THUMB_ROOT / draft_id / "artwork" / kind, filename)


def upload_cache_path(draft_id: str, filename: str) -> Path:
    return _safe_cache_path(UPLOAD_ROOT / draft_id, filename)


def extract_default_thumbnail(source: Path, target: Path, ratio: float = 0.5) -> Path:
    """Generate a 16:9 episode image while keeping the full video frame visible."""
    meta = probe_video(source)
    duration = float(meta.get("duration") or 0)
    if duration <= 0:
        raise ValueError(f"无法读取视频时长，不能自动生成单集封面：{source.name}")
    at = max(0.1, min(duration - 0.1, duration * ratio))
    return _render_artwork(source, target, "episode", at=at)
