"""YouTube uploader agent: uploads final video as a public YouTube Short."""

import os
import time
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from context import PipelineContext
from logger import get_logger, StepTimer

log = get_logger("youtube_uploader")

TOKEN_FILE = "youtube_token.json"
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5  # seconds


def _load_credentials() -> Credentials | None:
    """Load OAuth credentials from youtube_token.json."""
    if not os.path.exists(TOKEN_FILE):
        log.warning(f"  [YouTube Uploader] Token file not found: {TOKEN_FILE}")
        log.warning("  [YouTube Uploader] Run setup_youtube_auth.py first")
        return None

    try:
        creds = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
        )
        if not creds or not creds.valid:
            log.error("  [YouTube Uploader] Invalid credentials in token file")
            return None
        return creds
    except Exception as e:
        log.error(f"  [YouTube Uploader] Failed to load credentials: {e}")
        return None


def _upload_video(
    youtube,
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
) -> tuple[str | None, str | None]:
    """Upload video to YouTube.

    Returns:
        (video_id, video_url) or (None, None) on failure
    """

    # YouTube accepts 1:1 square or 9:16 vertical; <60s for Shorts
    body = {
        "snippet": {
            "title": title[:100],  # YouTube max: 100 chars
            "description": description[:5000],  # YouTube max: 5000 chars
            "tags": tags[:500],  # YouTube max: 500 tags
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024,  # 1 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    retry_count = 0

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                log.info(f"  [YouTube Uploader] Upload progress: {progress}%")

        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                # Retryable error
                retry_count += 1
                if retry_count > MAX_RETRIES:
                    log.error(f"  [YouTube Uploader] Max retries exceeded: {e}")
                    return None, None

                delay = RETRY_DELAY_BASE * (2 ** (retry_count - 1))
                log.warning(
                    f"  [YouTube Uploader] Retryable error {e.resp.status}, "
                    f"retrying in {delay}s... (attempt {retry_count}/{MAX_RETRIES})"
                )
                time.sleep(delay)
                continue
            else:
                # Non-retryable error
                log.error(f"  [YouTube Uploader] Upload failed: {e}")
                return None, None

        except Exception as e:
            log.error(f"  [YouTube Uploader] Unexpected error: {e}")
            return None, None

    if response and "id" in response:
        video_id = response["id"]
        video_url = f"https://www.youtube.com/shorts/{video_id}"
        return video_id, video_url

    log.error("  [YouTube Uploader] Upload succeeded but no video ID returned")
    return None, None


def _add_to_playlist(youtube, video_id: str, playlist_id: str) -> bool:
    """Add uploaded video to the Arbi playlist. Returns True on success."""
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()
        return True
    except HttpError as e:
        log.warning(f"  [YouTube Uploader] Failed to add to Arbi playlist: {e}")
        return False
    except Exception as e:
        log.warning(f"  [YouTube Uploader] Failed to add to Arbi playlist: {e}")
        return False


def upload_to_youtube(ctx: PipelineContext, config: dict) -> PipelineContext:
    """Upload final video to YouTube as a public Short.

    Automatic: runs whenever youtube_token.json exists, unless explicitly disabled.
    Set YOUTUBE_UPLOAD_ENABLED=false in .env to opt out.
    Non-fatal errors: pipeline continues even if upload fails.

    Requires:
    - youtube_token.json (run setup_youtube_auth.py once)
    """

    # Opt-out: explicit false disables upload
    if config.get("YOUTUBE_UPLOAD_ENABLED", "").lower() == "false":
        log.info("  [YouTube Uploader] Upload disabled (YOUTUBE_UPLOAD_ENABLED=false)")
        return ctx

    # Automatic: if no token file, skip without requiring any env var
    if not os.path.exists(TOKEN_FILE):
        log.info("  [YouTube Uploader] No token file; run setup_youtube_auth.py to enable auto-upload")
        return ctx

    # Get final video path
    video_path = ctx.final_video_path or ctx.subtitled_video_path or ctx.video_local_path
    if not video_path or not os.path.exists(video_path):
        log.error("  [YouTube Uploader] No video file found, skipping upload")
        ctx.errors.append("YouTube upload: no video file found")
        return ctx

    log.info("  [YouTube Uploader] Starting upload to YouTube...")

    with StepTimer(log, "YouTube upload") as t:
        # Load credentials
        creds = _load_credentials()
        if not creds:
            log.error("  [YouTube Uploader] Failed to load credentials, skipping upload")
            ctx.errors.append("YouTube upload: failed to load credentials")
            return ctx

        # Build YouTube API client
        try:
            youtube = build("youtube", "v3", credentials=creds)
        except Exception as e:
            log.error(f"  [YouTube Uploader] Failed to build YouTube client: {e}")
            ctx.errors.append(f"YouTube upload: failed to build client: {e}")
            return ctx

        # Prepare metadata
        title = ctx.event_title or "Arbi's Latest Adventure"
        description = (
            f"{ctx.event_description}\n\n"
            f"Watch Arbi re-enact this trending event with chaotic troll energy!\n\n"
            f"#Shorts #Arbi #Comedy"
        )
        tags = ["Shorts", "Arbi", "Comedy", "Animation"] + (ctx.video_keywords or [])

        # Upload video
        video_id, video_url = _upload_video(
            youtube,
            video_path,
            title,
            description,
            tags,
        )

        if not video_id:
            log.error("  [YouTube Uploader] Upload failed")
            ctx.errors.append("YouTube upload failed")
            return ctx

        # Add to Arbi playlist when YOUTUBE_ARBI_PLAYLIST_ID is set
        arbi_playlist_id = config.get("YOUTUBE_ARBI_PLAYLIST_ID", "").strip()
        if arbi_playlist_id:
            if _add_to_playlist(youtube, video_id, arbi_playlist_id):
                log.info(f"  [YouTube Uploader] Added to Arbi playlist")
            else:
                ctx.errors.append("YouTube: failed to add to Arbi playlist (upload succeeded)")

    log.info(f"  [YouTube Uploader] ✅ Uploaded: {video_url}")
    log.debug(f"  Upload took {t.elapsed:.2f}s")

    # Store upload info in context
    ctx.youtube_video_id = video_id
    ctx.youtube_video_url = video_url

    return ctx
