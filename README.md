# Arbi Flow

A video generation engine for **Arbi**, a wacky red furry troll character. Finds trending real-world events and produces animated square videos of Arbi re-enacting them with physical comedy, troll sounds, and overlays.

**Output:** ~13-second MP4 (1:1 square, H.264, 30fps) — 10s video + 3s outro — saved locally or optionally auto-uploaded to YouTube.

---

## Get Started with Cursor / Claude Code

The easiest way to run Arbi — no terminal experience needed. Claude guides you through every step.

**Prerequisites:** [Cursor](https://cursor.com) or [Claude Code](https://claude.ai/code) installed.

1. **Clone or use this template** on GitHub → open the folder in Cursor
2. **Type `/setup`** in the Cursor chat — Claude walks you through installing dependencies and getting your 4 API keys (~5 min)
3. **Type `/video`** — Claude runs the full pipeline and reports back when your video is ready

That's it. Each run takes ~5 minutes and costs ~$0.77.

**Other commands:**
- `/video-pick` — Scout finds 3 trending events, you choose which one Arbi re-enacts
- `/video-custom` — You name a specific event for Arbi to re-enact

---

## Quick Start (CLI)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Open .env and fill in your keys (see "API Keys" below)

# 3. Run the pipeline
python3 main.py                     # Full pipeline
python3 main.py --resume <run_id>   # Resume a failed run
python3 main.py --upload [run_id]   # Upload to YouTube (latest or specific run)
```

---

## Meet Arbi

Arbi is a wacky red furry monster with a gold crown, mismatched googly eyes, and a white fluffy belly. He's an internet troll personality — chaotic, mischievous, and hilariously unhinged. His character image lives at `artifacts/Character - New.png`.

When the pipeline finds a trending event, Arbi gets dressed in whatever the main person was wearing (suit, dress, jersey — you name it) and re-enacts the event with over-the-top physical comedy. Instead of narration, he makes troll sounds (gibberish, wacky noises, maniacal laughter).

### Using your own character

The repo includes Arbi's character image, outro clip, and background music so you can run it immediately. **To test your own character**, replace these files:

| File | Purpose | Replace with |
|------|---------|--------------|
| `artifacts/Character - New.png` | Reference image for the Character Dresser | Your character image (same pose/style works best) |
| `artifacts/outro.mp4` | 3-second branded clip at the end | Your own outro, or regenerate with `python3 scripts/generate_outro.py` |
| `artifacts/music/*.mp3` | Background music (optional) | Your own royalty-free tracks, or remove all to use troll voice only |

You'll also need to update the character description in `agents/cartoonist.py`, `agents/script_writer.py`, and `agents/video_producer.py` so the AI keeps your character's identity consistent.

---

## Video Pipeline (10 agents)

```
Video Scout → Video Finder → Video Analyzer → Character Dresser →
Animation Director → Video Producer → Troll Sound Designer →
Subtitle Burner → Outro Stitcher → YouTube Uploader (optional)
```

~5 minutes | ~$0.77 per run

### What Each Agent Does

| # | Agent | What It Does | API / Tool |
|---|-------|-------------|------------|
| 1 | **Video Scout** | Finds the most notable real-world event from the last 24 hours in mainstream media | Gemini (Google Search grounding) |
| 2 | **Video Finder** | Searches for the video URL, downloads it, extracts first frame | Serper + yt-dlp + ffmpeg |
| 3 | **Video Analyzer** | Watches the video, describes what happened, detects outfit & gender. Aligns scene prompt with Scout's chaos angle | Gemini 2.0 Flash (multimodal) |
| 4 | **Character Dresser** | Dresses Arbi in the main character's outfit, places him in the scene | Gemini Image Generation |
| 5 | **Animation Director** | Writes physical comedy animation direction for Arbi's troll behavior, prioritizing the chaos angle | Gemini 2.0 Flash |
| 6 | **Video Producer** | Animates the dressed Arbi with troll behavior, injecting chaos angle into Kling prompt | Kling 2.5 Turbo Pro (fal.ai) |
| 7 | **Troll Sound Designer** | Generates gibberish troll sounds with real keywords, composites onto video | ElevenLabs + ffmpeg |
| 8 | **Subtitle Burner** | Burns event title overlay at the top + timed keyword subtitles at the bottom | ffmpeg drawtext filter (optimized, 5-10x faster than old approach) |
| 9 | **Outro Stitcher** | Appends a 3-second branded Arbi outro clip to the end of the video | ffmpeg |
| 10 | **YouTube Uploader** | (Optional) Uploads final video to YouTube as a public Short | YouTube Data API v3 |

Each agent is a standalone Python function: `agent(ctx, config) -> ctx`. They communicate through a shared context dataclass. If any agent fails, the pipeline aborts immediately (except YouTube Uploader, which is non-fatal). **Exception:** if Video Finder cannot download any video for the chosen event, the pipeline switches to a different trending subject (up to 3 attempts) instead of failing.

---

## How It Works

### 1. Video Scout (`agents/video_scout.py`)

Searches for the most notable real-world event covered by mainstream media using Gemini with Google Search grounding. Covers all major categories: politics, entertainment, sports, tech, science, business, culture, weather, and more. Excludes social media-native content. Falls back through a cascade: **Gemini grounded** → Gemini plain → Perplexity.

Deduplication: checks `data/processed_events.json` to avoid covering the same event twice. When retrying after an undownloadable video, also excludes events we already tried.

### 2. Video Finder (`agents/video_finder.py`)

Uses Serper's video search API to find the actual video URL, then downloads it using yt-dlp. Extracts the first frame using ffmpeg. Downloads at max 720p, skips videos longer than 2 minutes, tries up to 10 candidate URLs. If no video can be downloaded, the pipeline switches to a different trending subject (up to 3 attempts).

### 3. Video Analyzer (`agents/video_analyzer.py`)

Uploads the downloaded video to Gemini's File API for multimodal analysis. Returns a play-by-play, scene prompt (aligned with chaos angle when provided), outfit description, gender, people count, and audio keywords for subtitle timing.

### 4. Character Dresser (`agents/cartoonist.py`)

Uses Gemini image generation to create Arbi wearing the detected outfit. 3-tier fallback: full prompt with reference image → simplified prompt → text-only → raw Character - New.png. Preserves Arbi's identity: red fur, gold crown, googly eyes.

### 5. Animation Director (`agents/script_writer.py`)

Writes a single physical comedy animation direction (15-25 words) describing what Arbi does. Prioritizes the chaos angle over scene context. Validated for word count with retries.

### 6. Video Producer (`agents/video_producer.py`)

Generates a 10-second animated video from the dressed Arbi image using Kling 2.5 Turbo Pro on fal.ai. Injects chaos angle into the Kling prompt for tone alignment. 1:1 square format.

### 7. Troll Sound Designer (`agents/voice_actor.py`)

Generates gibberish troll sounds using ElevenLabs with real keywords inserted. Pitch-shifted +30% for goblin effect. Optional background music from `artifacts/music/` at 25% volume. Composites audio onto video.

### 8. Subtitle Burner (`agents/subtitle_burner.py`)

Burns persistent event title (white, top) and timed keyword subtitles (yellow, bottom) onto every frame using PIL + ffmpeg.

### 9. Outro Stitcher (`agents/outro_stitcher.py`)

Appends a pre-rendered 3-second branded outro clip. Uses ffmpeg concat filter, normalizes to 1080x1080 @ 30fps.

### 10. YouTube Uploader (`agents/youtube_uploader.py`)

Uploads the final video to YouTube as a public Short. **Automatic:** runs on every pipeline run once `youtube_token.json` exists (no env var needed). Set `YOUTUBE_UPLOAD_ENABLED=false` in `.env` to disable. Non-fatal errors: pipeline continues even if upload fails. Includes retry logic with exponential backoff for transient API errors.

**Arbi playlist:** Set `YOUTUBE_ARBI_PLAYLIST_ID` in `.env` to add every uploaded video to your Arbi playlist. Create a playlist named "Arbi" on YouTube, then copy its ID from the URL (`youtube.com/playlist?list=PLxxxxxx`).

**One-time setup:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or use an existing one
3. Enable "YouTube Data API v3"
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Application type: "Desktop app"
6. Download the JSON credentials file and save as `client_secret.json` in the project root
7. Run: `python3 scripts/setup_youtube_auth.py`
8. A browser will open — sign in with your YouTube account and grant permissions
9. A `youtube_token.json` file will be created

After that, every pipeline run will automatically upload to YouTube. To opt out, add `YOUTUBE_UPLOAD_ENABLED=false` to `.env`.

**If you previously ran setup:** Re-run `python3 scripts/setup_youtube_auth.py` to grant playlist access (needed for Arbi playlist).

---

## API Keys

### Required

| Key | Service | What It Does | Get It At |
|-----|---------|-------------|-----------|
| `GEMINI_API_KEY` | Google Gemini | Trends + video analysis + character dressing + animation direction | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `SERPER_API_KEY` | Serper | Video search | [serper.dev](https://serper.dev) |
| `FAL_KEY` | fal.ai | Kling 2.5 Turbo Pro video generation | [fal.ai/dashboard/keys](https://fal.ai/dashboard/keys) |
| `ELEVENLABS_API_KEY` | ElevenLabs | Troll sound generation | [elevenlabs.io](https://elevenlabs.io) |

### Optional (extra trend sources)

| Key | Service | Get It At |
|-----|---------|-----------|
| `PERPLEXITY_API_KEY` | Perplexity (fallback trend detection) | [perplexity.ai](https://perplexity.ai) |

---

## Cost Per Run (~$0.77)

| Service | Purpose | Cost |
|---------|---------|------|
| Gemini 2.5 Flash (grounded) | Video Scout — find trending event | ~$0.005 |
| Serper | Video Finder — search for video URL | ~$0.002 |
| Gemini 2.5 Flash (multimodal) | Video Analyzer — understand video + detect outfit | ~$0.006 |
| Gemini 2.5 Flash Image | Character Dresser — dress Arbi in outfit | ~$0.04 |
| Gemini 2.5 Flash (text) | Animation Director — write animation direction | ~$0.001 |
| ElevenLabs (eleven_v3) | Troll Sound Designer — gibberish troll sounds | ~$0.02 |
| fal.ai (Kling 2.5 Turbo Pro) | Video Producer — animate Arbi (10s × $0.07/s) | ~$0.70 |
| Local tools | Subtitle Burner, Outro Stitcher | $0.00 |

---

## Where Outputs Go

| What | Location |
|------|----------|
| **Final video (ready to upload)** | `output/{Event_Title}_{run_id}.mp4` |
| **YouTube upload (if enabled)** | Auto-uploaded to your YouTube channel as a public video |
| YouTube video URL | Logged in `logs/{run_id}_summary.json` (`youtube_video_url` field) |
| Run log (human-readable) | `logs/{run_id}.log` |
| Run summary (JSON) | `logs/{run_id}_summary.json` |
| Processed events log | `data/processed_events.json` |

Intermediate artifacts (source video, dressed image, audio) are cleaned up after each run.

### Recovering failed runs

If the pipeline fails partway (e.g. Troll Sound Designer times out), you can finalize the run using the raw video that was already produced:

```bash
python3 finalize_run.py [run_id]
```

Example: `python3 finalize_run.py 1e9bbcb7` — runs Troll Sound Designer, Subtitle Burner, and Outro Stitcher on the existing `{run_id}_final.mp4`, then copies the result to `output/`. Requires the run's summary JSON and the raw video in `artifacts/videos/`.

---

## System Dependencies

| Tool | Purpose | Install |
|------|---------|---------|
| **ffmpeg** | Frame extraction, audio composite, video re-encoding | `brew install ffmpeg` (macOS) |
| **Python 3.10+** | Runtime | [python.org](https://python.org) |

---

## FAQ

### How do I customize the Character Dresser prompt?

Edit the `_build_dresser_prompt()` function in `agents/cartoonist.py`.

### How do I change the animation style?

Edit the `SYSTEM_PROMPT` in `agents/script_writer.py`.

### How do I change the troll voice?

Edit `agents/voice_actor.py`:
- `TROLL_VOICE` — swap the voice ID (current: Patrick, shouty gaming voice)
- `stability` — lower = more chaotic (current: 0.0)
- `similarity_boost` — lower = more distorted (current: 0.3)
- `style` — higher = more exaggerated personality (current: 1.0)
- `speed` — higher = more manic (current: 1.4)
- `PITCH_SHIFT_FACTOR` — >1.0 = higher goblin pitch, <1.0 = deeper ogre pitch (current: 1.3)

### How do I customize the background music?

Drop `.mp3`, `.wav`, or `.m4a` files into `artifacts/music/`. The pipeline randomly picks one per run, trims it to video length, and mixes it at 25% volume. To disable, remove all files from `artifacts/music/`.

### How do I use a different character instead of Arbi?

Replace `artifacts/Character - New.png` with your character image and update the character description in `cartoonist.py`, `script_writer.py`, and `video_producer.py`.

### What if an agent fails?

The pipeline aborts immediately. Common failures:
- **Rate limits (429):** Video Scout has built-in retry. Wait and retry.
- **yt-dlp download fails:** Video Finder tries up to 5 candidate URLs.
- **Content safety blocks:** Character Dresser falls back through 3 tiers.
- **fal.ai timeout:** Transient network issue. Retry the pipeline.

### How do I reset the processed events list?

```bash
echo '{"processed": []}' > data/processed_events.json
```

### How do I change the video duration or aspect ratio?

Edit `agents/video_producer.py`:
- **Duration:** Change `KLING_DURATION` in `video_producer.py` to `"5"` or `"10"` (Kling 2.5 Turbo Pro supports 5–10s)
- **Aspect ratio:** Change `"aspect_ratio": "1:1"` to `"9:16"` or `"16:9"` for vertical/landscape

---

## Project Structure

```
New Arbi/
├── main.py                     # Entry point — runs video pipeline
├── orchestrator.py             # Pipeline runner (config, logging, agent loop)
├── config.py                   # Loads .env, validates API keys
├── dedup.py                    # Tracks processed events (avoid repeats)
├── logger.py                   # Logging setup
├── generate_outro.py           # Regenerate the branded Arbi outro clip
├── context/
│   ├── base.py                 # BaseContext — shared pipeline state
│   └── video.py                # VideoContext — video-specific fields
├── pipelines/
│   └── video.py                # Video pipeline (9 agents)
├── agents/
│   ├── arbi_persona.py         # Arbi's persona and content boundaries
│   ├── video_scout.py          # Find trending real-world event
│   ├── video_finder.py         # Download video + extract first frame
│   ├── video_analyzer.py       # Analyze video + detect outfit
│   ├── cartoonist.py           # Dress Arbi in detected outfit
│   ├── script_writer.py        # Write animation direction
│   ├── video_producer.py       # Animate dressed Arbi (Kling 2.5 Turbo Pro)
│   ├── voice_actor.py          # Generate troll sounds (ElevenLabs)
│   ├── subtitle_burner.py      # Add event title overlay
│   ├── outro_stitcher.py       # Append branded outro
│   └── youtube_uploader.py     # Upload to YouTube (automatic when token exists)
├── scripts/
│   └── setup_youtube_auth.py   # One-time OAuth setup for YouTube uploads
├── .claude/
│   └── commands/
│       ├── setup.md            # /setup skill — first-time onboarding
│       ├── video.md            # /video skill — auto-pick trending event
│       ├── video-pick.md       # /video-pick skill — choose from 3 events
│       └── video-custom.md     # /video-custom skill — pin your own event
├── artifacts/
│   ├── Character - New.png     # Arbi character reference image
│   ├── outro.mp4               # Pre-rendered 3s branded outro clip
│   ├── images/                 # Generated images (cleaned per run)
│   ├── audio/                  # Audio files (cleaned per run)
│   ├── music/                  # Background music library (royalty-free)
│   └── videos/                 # Video files (cleaned per run)
├── data/                       # Processed events log
├── logs/                       # Run logs and summaries
├── output/                     # Final videos ready for upload
├── .env                        # Your API keys (not committed)
├── .env.example                # Template
├── .gitignore
└── requirements.txt
```
