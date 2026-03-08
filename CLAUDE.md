# Arbi Flow — Project Guide for Claude

## What This Is

**Arbi Flow** is a video generation engine for **Arbi**, a wacky red furry troll character. It finds trending real-world events and produces animated square videos of Arbi re-enacting them with physical comedy, troll sounds, and overlays. Videos are saved locally or optionally auto-uploaded to YouTube.

## Pipeline

| Pipeline | Command | Skill | What It Produces | Time | Cost |
|----------|---------|-------|-----------------|------|------|
| **Video** | `python3 main.py` | `/video` | Animated video of Arbi re-enacting event (~13s, 1:1) | ~5 min | ~$0.77 |

## Tech Stack

- **Python 3.10+** — all source code
- **Google Gemini 2.5 Flash** — trend detection, video analysis, image generation, text generation
- **fal.ai (Kling 2.5 Turbo Pro)** — AI video generation from image
- **ElevenLabs** — text-to-speech troll sounds
- **Serper** — video search
- **ffmpeg** — frame extraction, audio compositing, video encoding (system dep)
- **yt-dlp** — video downloading

## How to Run

```bash
pip install -r requirements.txt
cp .env.example .env                # fill in API keys
python3 main.py                     # run full video pipeline (~5 min, ~$0.77)
python3 main.py --resume <run_id>   # resume a failed run from last step
python3 main.py --upload [run_id]   # upload to YouTube (latest or specific run)
```

Or use Claude Code skill: `/video`

## Architecture

```
main.py → pipelines/video.py → orchestrator.py → 10 agents:
  1. Video Scout      (Gemini grounded → Perplexity)
  2. Video Finder     (Serper + yt-dlp)
  3. Video Analyzer   (Gemini multimodal)
  4. Character Dresser (Gemini image gen)
  5. Animation Director (Gemini)
  6. Video Producer   (fal.ai Kling 2.5 Turbo Pro)
  7. Troll Sound Designer (ElevenLabs + ffmpeg)
  8. Subtitle Burner  (ffmpeg)
  9. Outro Stitcher   (ffmpeg)
 10. YouTube Uploader (YouTube Data API v3, optional)
```

### Video Pipeline (10 agents)

| # | Agent | File | What It Does |
|---|-------|------|-------------|
| 1 | Video Scout | `agents/video_scout.py` | Finds trending event (Gemini grounded → Perplexity fallback) |
| 2 | Video Finder | `agents/video_finder.py` | Searches + downloads source video via Serper + yt-dlp |
| 3 | Video Analyzer | `agents/video_analyzer.py` | Analyzes video with Gemini multimodal → outfit, keywords, scene (aligned with chaos angle) |
| 4 | Character Dresser | `agents/cartoonist.py` | Dresses Arbi in detected outfit (Gemini image gen, 3-tier fallback) |
| 5 | Animation Director | `agents/script_writer.py` | Writes 15-25 word physical comedy direction (prioritizes chaos angle) |
| 6 | Video Producer | `agents/video_producer.py` | Generates 10s animated video via Kling 2.5 Turbo Pro on fal.ai (injects chaos angle into prompt) |
| 7 | Troll Sound Designer | `agents/voice_actor.py` | Gibberish troll audio via ElevenLabs + pitch shift |
| 8 | Subtitle Burner | `agents/subtitle_burner.py` | Burns event title + keyword overlays onto video |
| 9 | Outro Stitcher | `agents/outro_stitcher.py` | Appends 3s branded outro clip |
| 10 | YouTube Uploader | `agents/youtube_uploader.py` | Uploads final video to YouTube (automatic when token exists, non-fatal) |

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point with CLI: `python main.py [--resume\|--upload <run_id>]` |
| `orchestrator.py` | Pipeline runner (config, logging, agent loop, summary, auto-cleanup) |
| `config.py` | Loads `.env`, validates required API keys |
| `dedup.py` | Prevents reprocessing same events (with file locking for concurrent runs) |
| `logger.py` | Logging setup: console (INFO), file (DEBUG), JSON summary |
| `context/base.py` | `BaseContext` dataclass — shared pipeline state |
| `context/video.py` | `VideoContext(BaseContext)` — video-specific fields |
| `pipelines/video.py` | Video pipeline definition (agent list + context factory) |
| `agents/arbi_persona.py` | Arbi's personality, visual identity, content boundaries |
| `utils/*.py` | Shared utilities (JSON parsing, ffmpeg wrappers, video processing) |
| `scripts/setup_youtube_auth.py` | One-time OAuth setup for YouTube uploads |
| `scripts/generate_outro.py` | Regenerate branded outro clip |
## Directory Layout

```
main.py                   # Entry point — runs video pipeline, --resume, --upload
orchestrator.py           # Pipeline runner with auto-cleanup
config.py                 # Loads .env, validates API keys
dedup.py                  # Tracks processed events (with file locking)
logger.py                 # Logging setup
context/
  base.py               # BaseContext — shared pipeline state
  video.py              # VideoContext — video-specific fields
pipelines/
  video.py              # Video pipeline (10 agents)
agents/
  arbi_persona.py       # Character definition + content boundaries
  video_scout.py        # Finds trending events
  video_finder.py       # Downloads source video
  video_analyzer.py     # Analyzes video
  cartoonist.py         # Dresses Arbi
  script_writer.py      # Animation direction
  video_producer.py     # Generates animated video
  voice_actor.py        # Troll sounds
  subtitle_burner.py    # Burns overlays (optimized ffmpeg drawtext)
  outro_stitcher.py     # Appends outro
  youtube_uploader.py   # Uploads to YouTube (automatic when token exists)
utils/                    # Shared utilities
  json_utils.py         # LLM JSON parsing
  ffmpeg_utils.py       # ffmpeg wrappers (run, metadata, trim, etc.)
  video_utils.py        # Video processing (square conversion, concat)
scripts/                  # One-time/rare utilities
  setup_youtube_auth.py # OAuth setup for YouTube
  generate_outro.py     # Regenerate branded outro clip
artifacts/
  Character - New.png   # Arbi reference image
  outro.mp4             # Pre-rendered 3s branded outro
  images/               # Generated images (cleaned per run)
  audio/                # Audio files (cleaned per run)
  videos/               # Video files (cleaned per run)
  music/                # Background music library
data/
  processed_events.json # Dedup tracking
  trend_cache.json      # Cached trends
logs/
  {run_id}.log          # Debug log
  {run_id}_summary.json # Machine-readable run summary
output/                   # Final videos ready for upload
.claude/
  commands/
    video.md            # /video skill
```

## Context

```
BaseContext (context/base.py) — run metadata, event discovery, media paths, errors
└── VideoContext (context/video.py) — video-specific fields (source video, analysis, animation, audio)
```

## Required Environment Variables

```
GEMINI_API_KEY, SERPER_API_KEY, FAL_KEY, ELEVENLABS_API_KEY
```

Optional:
- `PERPLEXITY_API_KEY` (fallback trend source)
- `YOUTUBE_UPLOAD_ENABLED=false` (opt-out: disable auto-upload; upload is automatic when `youtube_token.json` exists)
- `YOUTUBE_ARBI_PLAYLIST_ID` (Arbi playlist ID — every video is added to this playlist)

## Conventions

- Agent functions: `agent_name(ctx, config) -> ctx`
- Output files: `{run_id}_description.ext` (e.g., `7a7d12c4_final_with_outro.mp4`)
- Final video: copied to `output/` with clean event title filename
- Cascading fallbacks everywhere (Gemini grounded → Gemini plain → Perplexity; multi-tier image gen)
- Arbi's identity MUST be preserved across all image/video generation — red furry monster, gold crown, googly eyes
- Video format: MP4 H.264, 1:1 aspect ratio, 30fps, ~13s (10s + 3s outro)
- JSON responses from LLMs: strip markdown fences before parsing
- No automated tests — verify via logs and generated output
- Claude Code skill in `.claude/commands/video.md` triggers the pipeline
- **Subject switch on undownloadable video**: If Video Finder cannot download any video for the chosen event, the pipeline switches to a different trending subject (up to 3 attempts). Failed events are excluded from Video Scout so we do not retry the same undownloadable event.

## Character: Arbi

Red furry monster with gold crown (tilted), mismatched googly eyes, white fluffy belly. Pixar 3D style. Chaotic neutral troll energy — causes hilarious mayhem but never mean-spirited. Persona details in `agents/arbi_persona.py`.

## Post-Edit Checklist

After making any code change, always check if `README.md` needs updating. Update it when:

- The agent sequence changes
- An agent is added, removed, renamed, or its behavior changes
- New environment variables or dependencies are added/removed
- The output format or cost changes
- New files/directories are introduced or existing ones moved
- Run commands, setup steps, or system requirements change
- `CLAUDE.md` itself should also be kept in sync with any structural changes
