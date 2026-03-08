"""ffmpeg utilities for video processing."""

import json
import subprocess
from typing import Tuple

from logger import get_logger

log = get_logger("ffmpeg_utils")


def run_ffmpeg(
    args: list[str],
    timeout: int = 60,
    description: str = "ffmpeg operation"
) -> subprocess.CompletedProcess:
    """Run ffmpeg with consistent error handling and logging.

    Args:
        args: Full ffmpeg command args (starting with "ffmpeg")
        timeout: Timeout in seconds
        description: Human-readable description for logging

    Returns:
        CompletedProcess result

    Raises:
        RuntimeError: If ffmpeg fails or times out
    """
    log.debug(f"Running: {' '.join(args[:5])}...")

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{description} timed out after {timeout}s") from e

    if result.returncode != 0:
        # Skip the verbose ffmpeg version/config header and grab the last 800 chars
        # which contain the actual error message.
        stderr = result.stderr or ""
        error_msg = stderr[-800:] if len(stderr) > 800 else stderr or "Unknown error"
        raise RuntimeError(f"{description} failed: {error_msg}")

    return result


def get_video_metadata(video_path: str) -> dict:
    """Extract video metadata using ffprobe.

    Args:
        video_path: Path to video file

    Returns:
        Dictionary with width, height, fps, duration, codec

    Raises:
        RuntimeError: If ffprobe fails
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffprobe timed out on {video_path}") from e

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:500]}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe returned invalid JSON: {e}") from e

    # Find video stream
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None
    )

    if not video_stream:
        raise RuntimeError(f"No video stream found in {video_path}")

    # Parse FPS (may be fraction like "30/1")
    fps_str = video_stream.get("r_frame_rate", "30/1")
    try:
        if "/" in fps_str:
            num, denom = fps_str.split("/")
            fps = float(num) / float(denom)
        else:
            fps = float(fps_str)
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    return {
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "duration": float(data.get("format", {}).get("duration", 0)),
        "codec": video_stream.get("codec_name", "unknown"),
    }


def extract_first_frame(video_path: str, output_path: str, quality: int = 2) -> str:
    """Extract first frame of video as JPEG.

    Args:
        video_path: Input video
        output_path: Output image path
        quality: JPEG quality (1-31, lower is better)

    Returns:
        Path to extracted frame

    Raises:
        RuntimeError: If extraction fails
    """
    run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", str(quality),
            output_path,
        ],
        timeout=30,
        description="Extract first frame"
    )

    return output_path


def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds.

    Args:
        audio_path: Path to audio file

    Returns:
        Duration in seconds

    Raises:
        RuntimeError: If ffprobe fails
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffprobe timed out on {audio_path}") from e

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    try:
        return float(result.stdout.strip())
    except ValueError as e:
        raise RuntimeError(f"Invalid duration from ffprobe: {result.stdout}") from e


def trim_video(input_path: str, output_path: str, duration: int, codec_copy: bool = True) -> str:
    """Trim video to specified duration.

    Args:
        input_path: Input video
        output_path: Output video
        duration: Duration in seconds
        codec_copy: Use codec copy (faster) instead of re-encoding

    Returns:
        Path to trimmed video

    Raises:
        RuntimeError: If trim fails
    """
    codec_args = ["-c", "copy"] if codec_copy else ["-c:v", "libx264", "-c:a", "aac"]

    run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-t", str(duration),
            *codec_args,
            output_path,
        ],
        timeout=120,
        description=f"Trim video to {duration}s"
    )

    return output_path


def trim_audio(input_path: str, output_path: str, duration: float) -> str:
    """Trim audio to specified duration.

    Args:
        input_path: Input audio
        output_path: Output audio
        duration: Duration in seconds

    Returns:
        Path to trimmed audio

    Raises:
        RuntimeError: If trim fails
    """
    run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-t", str(duration),
            "-c", "copy",
            output_path,
        ],
        timeout=30,
        description=f"Trim audio to {duration}s"
    )

    return output_path


def pitch_shift_audio(
    input_path: str,
    output_path: str,
    semitones: int,
    tempo_factor: float = 1.0
) -> str:
    """Pitch shift audio using rubberband filter.

    Args:
        input_path: Input audio
        output_path: Output audio
        semitones: Pitch shift in semitones (+/-)
        tempo_factor: Tempo multiplier (1.0 = no change)

    Returns:
        Path to pitch-shifted audio

    Raises:
        RuntimeError: If pitch shift fails
    """
    # Convert semitones to frequency ratio
    pitch_ratio = 2.0 ** (semitones / 12.0)

    run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", f"rubberband=pitch={pitch_ratio}:tempo={tempo_factor}",
            output_path,
        ],
        timeout=60,
        description=f"Pitch shift by {semitones} semitones"
    )

    return output_path
