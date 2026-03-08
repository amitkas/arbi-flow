"""Subtitle burner - renders text overlays via PIL then composites with ffmpeg overlay filter.

Uses PIL (Pillow) to render transparent RGBA overlay images and ffmpeg's overlay filter
to composite them onto the video. This approach works regardless of ffmpeg build flags
(no libfreetype / drawtext dependency).
"""

import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from context import PipelineContext
from logger import get_logger, StepTimer
from utils.ffmpeg_utils import run_ffmpeg, get_video_metadata

log = get_logger("subtitle_burner")

# Ordered list of font candidates; first one found is used
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def burn_subtitles(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Add event title overlay and keyword subtitles to the video.

    Renders text to transparent PNG images via PIL then composites onto the
    video with ffmpeg's overlay filter.
    """

    if not ctx.video_local_path or not os.path.exists(ctx.video_local_path):
        log.error("  [Subtitle Burner] No video file found, skipping overlays")
        ctx.subtitled_video_path = ctx.video_local_path
        return ctx

    event_text = ctx.event_title.upper() if ctx.event_title else ""
    if not event_text:
        log.info("  [Subtitle Burner] No event title, skipping overlays")
        ctx.subtitled_video_path = ctx.video_local_path
        return ctx

    log.info(f"  [Subtitle Burner] Event title overlay: {event_text}")

    artifacts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")
    images_dir = os.path.join(artifacts_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    subtitled_path = os.path.join(
        artifacts_dir, "videos", f"{ctx.run_id}_final_subtitled.mp4"
    )

    # Get video dimensions for positioning
    metadata = get_video_metadata(ctx.video_local_path)
    width = metadata["width"]
    height = metadata["height"]
    log.debug(f"  Video: {width}x{height} @ {metadata['fps']}fps")

    font_path = _find_font()
    if not font_path:
        log.warning("  [Subtitle Burner] No TrueType font found; text will use bitmap fallback")

    # Font sizes and positions scaled to video dimensions
    title_font_size = width // 20
    title_y_pos = height // 15
    keyword_font_size = width // 14
    keyword_y_pos = int(height * 0.75)

    # Build list of (overlay_png_path, start_sec, end_sec) tuples.
    # start/end = None means the overlay is persistent (full duration).
    overlays: list[tuple[str, Optional[float], Optional[float]]] = []

    # --- Event title (persistent) ---
    title_path = os.path.join(images_dir, f"{ctx.run_id}_overlay_title.png")
    title_img = _render_text_image(
        text=event_text,
        width=width,
        height=height,
        font_size=title_font_size,
        text_color=(255, 255, 255, 255),
        y_pos=title_y_pos,
        font_path=font_path,
        border_width=4,
        show_background=False,
    )
    title_img.save(title_path)
    overlays.append((title_path, None, None))

    # --- Keyword subtitles (timed) ---
    word_timestamps = ctx.word_timestamps or []
    if word_timestamps:
        log.info(f"  [Subtitle Burner] Adding {len(word_timestamps)} keyword subtitle(s)")
        for i, ts in enumerate(word_timestamps):
            kw_text = ts["word"].upper()
            kw_path = os.path.join(images_dir, f"{ctx.run_id}_overlay_kw{i}.png")
            kw_img = _render_text_image(
                text=kw_text,
                width=width,
                height=height,
                font_size=keyword_font_size,
                text_color=(255, 255, 0, 255),
                y_pos=keyword_y_pos,
                font_path=font_path,
                border_width=5,
            )
            kw_img.save(kw_path)
            overlays.append((kw_path, ts["start"], ts["end"]))

    # --- Build ffmpeg command ---
    # Inputs: [0] video, [1..N] overlay PNGs
    cmd = ["ffmpeg", "-y", "-i", ctx.video_local_path]
    for path, _, _ in overlays:
        cmd.extend(["-i", path])

    # Build filter_complex: chain overlays one by one
    filter_parts = []
    prev = "0:v"
    for i, (_, start, end) in enumerate(overlays):
        input_idx = i + 1
        curr = f"v{i}"
        enable = f":enable='between(t,{start},{end})'" if start is not None else ""
        filter_parts.append(f"[{prev}][{input_idx}:v]overlay=format=auto{enable}[{curr}]")
        prev = curr

    filter_complex = ";".join(filter_parts)

    log.info("  [Subtitle Burner] Burning overlays with PIL + ffmpeg overlay filter...")

    with StepTimer(log, "Burn subtitles") as t:
        try:
            run_ffmpeg(
                [
                    *cmd,
                    "-filter_complex", filter_complex,
                    "-map", f"[{prev}]",
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "18",
                    "-c:a", "copy",
                    subtitled_path,
                ],
                timeout=180,
                description="Burn subtitles with overlay filter",
            )
        except RuntimeError as e:
            log.error(f"  [Subtitle Burner] Failed to burn subtitles: {e}")
            ctx.subtitled_video_path = ctx.video_local_path
            return ctx

    file_size_mb = os.path.getsize(subtitled_path) / (1024 * 1024)
    log.info(
        f"  [Subtitle Burner] Subtitled video: {subtitled_path} "
        f"({file_size_mb:.1f} MB, {t.elapsed:.1f}s)"
    )

    ctx.subtitled_video_path = subtitled_path
    return ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_font() -> Optional[str]:
    """Return the path to the first available TrueType font."""
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _load_font(font_size: int, font_path: Optional[str]) -> ImageFont.ImageFont:
    """Load a TrueType font at *font_size*, falling back to the bitmap default."""
    candidates = ([font_path] if font_path else []) + [
        p for p in _FONT_CANDIDATES if p != font_path
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, font_size)
            except Exception:
                continue
    return ImageFont.load_default()


def _render_text_image(
    text: str,
    width: int,
    height: int,
    font_size: int,
    text_color: tuple,
    y_pos: int,
    font_path: Optional[str],
    border_width: int = 3,
    show_background: bool = True,
) -> Image.Image:
    """Render *text* centered horizontally at *y_pos* onto a transparent RGBA canvas.

    Produces a full-frame (width × height) image so it can be composited directly
    via ffmpeg overlay=0:0 without needing per-overlay position arguments.
    Long text is automatically word-wrapped to fit within the video width.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    font = _load_font(font_size, font_path)

    max_text_width = int(width * 0.92)  # 92% of video width as max line width
    wrapped = _wrap_text(text, font, max_text_width)

    # Measure full wrapped block
    draw = ImageDraw.Draw(img)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=6)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2

    # Optional semi-transparent background box
    if show_background:
        pad = 20
        box_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(box_layer).rectangle(
            [x - pad, y_pos - pad, x + text_w + pad, y_pos + text_h + pad],
            fill=(0, 0, 0, int(0.6 * 255)),
        )
        img = Image.alpha_composite(img, box_layer)

    # Text with black stroke for legibility
    ImageDraw.Draw(img).multiline_text(
        (x, y_pos),
        wrapped,
        font=font,
        fill=text_color,
        spacing=6,
        align="center",
        stroke_width=border_width,
        stroke_fill=(0, 0, 0, 255),
    )

    return img


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    """Word-wrap *text* so no line exceeds *max_width* pixels with *font*."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)

    for word in words:
        candidate = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)

    if current:
        lines.append(" ".join(current))

    return "\n".join(lines)
