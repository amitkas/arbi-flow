import os
import time
import requests
import fal_client
from PIL import Image

from context import PipelineContext
from logger import get_logger, StepTimer

log = get_logger("video_producer")

# Retry config for fal.ai upload (often hits 408 Timeout)
UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_DELAY_SEC = 10
UPLOAD_TIMEOUT_SEC = 120

# Target 1:1 dimensions for Kling (square). Kling often follows input image aspect ratio.
TARGET_1_1_SIZE = 576

# Kling 2.5 Turbo Pro supports 5 or 10 seconds. 10s = ~$0.70; 5s = ~$0.35.
KLING_DURATION = "10"


def _ensure_image_1_1(image_path: str) -> str:
    """Crop/resize image to 1:1 so Kling receives a square image and returns 1:1 video.
    Returns path to the 1:1 image (same dir as input, _1x1.jpg)."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    # Desired aspect ratio 1:1 (square)
    target_ratio = 1.0
    current_ratio = w / h

    if abs(current_ratio - target_ratio) < 0.02:
        log.debug(f"  [Video Producer] Image already ~1:1 ({w}x{h}), resizing to {TARGET_1_1_SIZE}x{TARGET_1_1_SIZE}")
        img = img.resize((TARGET_1_1_SIZE, TARGET_1_1_SIZE), Image.Resampling.LANCZOS)
    elif current_ratio > target_ratio:
        # Too wide: center-crop width to get 1:1
        new_w = h
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
        log.info(f"  [Video Producer] Cropped image to 1:1 ({w}x{h} -> {new_w}x{h})")
        img = img.resize((TARGET_1_1_SIZE, TARGET_1_1_SIZE), Image.Resampling.LANCZOS)
    else:
        # Too tall: center-crop height to get 1:1
        new_h = w
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
        log.info(f"  [Video Producer] Cropped image to 1:1 ({w}x{h} -> {w}x{new_h})")
        img = img.resize((TARGET_1_1_SIZE, TARGET_1_1_SIZE), Image.Resampling.LANCZOS)

    base, _ = os.path.splitext(image_path)
    out_path = f"{base}_1x1.jpg"
    img.save(out_path, "JPEG", quality=92)
    log.debug(f"  [Video Producer] Saved 1:1 image: {out_path} ({TARGET_1_1_SIZE}x{TARGET_1_1_SIZE})")
    return out_path


def produce_video(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Generate a 1:1 square video from the cartoon image using Kling 2.5 Turbo Pro on fal.ai."""

    os.environ["FAL_KEY"] = config["FAL_KEY"]

    # Step 0: Force cartoon image to 1:1 so Kling outputs 1:1 (it often follows input aspect ratio)
    image_to_upload = ctx.cartoon_image_path
    if image_to_upload and os.path.exists(image_to_upload):
        with StepTimer(log, "Ensure image 1:1"):
            image_to_upload = _ensure_image_1_1(image_to_upload)

    # Step 1: Upload the cartoon image to fal.ai (with retries and longer timeout)
    log.info("  [Video Producer] Uploading cartoon image to fal.ai...")
    log.debug(f"  Image path: {image_to_upload}")
    log.debug(f"  Image size: {os.path.getsize(image_to_upload)} bytes")

    client = fal_client.SyncClient(default_timeout=UPLOAD_TIMEOUT_SEC)
    image_url = None
    last_error = None
    with StepTimer(log, "fal.ai image upload"):
        for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
            try:
                image_url = client.upload_file(image_to_upload)
                break
            except Exception as e:
                last_error = e
                if attempt < UPLOAD_MAX_ATTEMPTS:
                    log.warning(
                        f"  [Video Producer] Upload attempt {attempt}/{UPLOAD_MAX_ATTEMPTS} failed: {e}. "
                        f"Retrying in {UPLOAD_RETRY_DELAY_SEC}s..."
                    )
                    time.sleep(UPLOAD_RETRY_DELAY_SEC)
                else:
                    raise
    if not image_url:
        raise last_error or RuntimeError("fal.ai image upload failed")
    log.info(f"  [Video Producer] Image uploaded: {image_url[:80]}...")
    log.debug(f"  Full upload URL: {image_url}")

    # Step 2: Submit video generation job with Arbi-specific prompt
    # The animation direction already incorporates the chaos angle (script writer
    # treats it as PRIMARY input). Don't dump the raw chaos_angle narrative — it's
    # prose comedy that confuses the video model. Lead with the visual direction.
    animation_cue = ctx.animation_direction if ctx.animation_direction else ctx.scene_prompt
    event_context = f"Scene: {ctx.event_title}. " if ctx.event_title else ""

    video_prompt = (
        f"Pixar 3D animation style. {event_context}{animation_cue}. "
        f"Smooth continuous motion, steady camera. Vibrant lighting."
    )
    log.debug(f"  Video prompt ({len(video_prompt)} chars): {video_prompt}")

    log.info("  [Video Producer] Submitting video generation job (Kling 2.5 Turbo Pro)...")
    log.info("  [Video Producer] This may take 2-5 minutes...")

    fal_arguments = {
        "image_url": image_url,
        "prompt": video_prompt,
        "duration": KLING_DURATION,
    }
    log.debug(f"  fal.ai arguments: {fal_arguments}")

    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for entry in update.logs:
                log.info(f"    [fal.ai] {entry['message']}")

    with StepTimer(log, "Kling 2.5 Turbo Pro video generation") as t:
        result = fal_client.subscribe(
            "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
            arguments=fal_arguments,
            with_logs=True,
            on_queue_update=on_queue_update,
        )

    log.debug(f"  Video generation completed in {t.elapsed:.2f}s")
    log.debug(f"  fal.ai result keys: {list(result.keys())}")

    # Step 3: Download the generated video
    video_url = result["video"]["url"]
    log.info(f"  [Video Producer] Video ready: {video_url[:80]}...")
    log.debug(f"  Full video URL: {video_url}")

    artifacts_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "artifacts", "videos"
    )
    os.makedirs(artifacts_dir, exist_ok=True)

    video_path = os.path.join(artifacts_dir, f"{ctx.run_id}_final.mp4")

    log.info("  [Video Producer] Downloading video...")
    with StepTimer(log, "Video download") as t:
        resp = requests.get(video_url, stream=True, timeout=120)
        resp.raise_for_status()

        with open(video_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    log.info(f"  [Video Producer] Saved: {video_path} ({file_size_mb:.1f} MB)")
    log.debug(f"  Download took {t.elapsed:.2f}s, file size: {file_size_mb:.2f} MB")

    ctx.video_local_path = video_path
    return ctx
