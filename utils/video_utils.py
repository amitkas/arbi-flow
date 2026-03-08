"""Video processing utilities."""

import os
from PIL import Image, ImageOps

from .ffmpeg_utils import run_ffmpeg


def make_square_video(input_path: str, output_path: str, size: int = 1080) -> str:
    """Convert video to square aspect ratio by center-cropping.

    Args:
        input_path: Input video
        output_path: Output video
        size: Target size (width and height)

    Returns:
        Path to square video

    Raises:
        RuntimeError: If conversion fails
    """
    # Use ffmpeg's crop and scale filters to center-crop to square
    run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", f"crop=min(iw\\,ih):min(iw\\,ih),scale={size}:{size}",
            "-c:v", "libx264",
            "-c:a", "copy",
            "-preset", "fast",
            output_path,
        ],
        timeout=120,
        description="Convert to square video"
    )

    return output_path


def make_square_image(input_path: str, output_path: str, size: int = 1080) -> str:
    """Convert image to square aspect ratio by center-cropping.

    Args:
        input_path: Input image
        output_path: Output image
        size: Target size (width and height)

    Returns:
        Path to square image

    Raises:
        RuntimeError: If conversion fails
    """
    img = Image.open(input_path).convert("RGB")

    # Use PIL's ImageOps.fit for center-crop
    img_square = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)

    img_square.save(output_path, "JPEG", quality=95)

    return output_path


def concatenate_videos(
    video_paths: list[str],
    output_path: str,
    normalize: bool = True
) -> str:
    """Concatenate multiple videos into one.

    Args:
        video_paths: List of input video paths
        output_path: Output video path
        normalize: Normalize resolution/fps/codec before concatenating

    Returns:
        Path to concatenated video

    Raises:
        RuntimeError: If concatenation fails
    """
    if len(video_paths) < 2:
        raise ValueError("Need at least 2 videos to concatenate")

    # Create concat list file
    concat_list_path = output_path + ".concat.txt"
    with open(concat_list_path, "w") as f:
        for path in video_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    try:
        if normalize:
            # Use concat filter for normalization
            run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-preset", "fast",
                    output_path,
                ],
                timeout=180,
                description="Concatenate videos (normalized)"
            )
        else:
            # Simple concat (requires same format)
            run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy",
                    output_path,
                ],
                timeout=180,
                description="Concatenate videos (copy)"
            )
    finally:
        # Clean up concat list
        if os.path.exists(concat_list_path):
            os.remove(concat_list_path)

    return output_path
