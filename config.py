import os
from dotenv import load_dotenv


REQUIRED_KEYS = [
    "SERPER_API_KEY",
    "GEMINI_API_KEY",
    "FAL_KEY",
    "ELEVENLABS_API_KEY",
]

OPTIONAL_KEYS = [
    "PERPLEXITY_API_KEY",
    "YT_DLP_COOKIES",           # Path to cookies.txt for YouTube (export from browser)
    "YT_DLP_COOKIES_FROM_BROWSER",  # e.g. "chrome" or "firefox" — use browser cookies
    "YOUTUBE_UPLOAD_ENABLED",   # Set to "true" to enable auto-upload to YouTube
    "YOUTUBE_ARBI_PLAYLIST_ID", # Arbi playlist ID — every video is added to this playlist
]


def load_config() -> dict:
    load_dotenv()

    config = {}
    missing = []

    for key in REQUIRED_KEYS:
        value = os.getenv(key, "").strip()
        if not value:
            missing.append(key)
        config[key] = value

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in the values."
        )

    for key in OPTIONAL_KEYS:
        config[key] = os.getenv(key, "").strip()

    return config
