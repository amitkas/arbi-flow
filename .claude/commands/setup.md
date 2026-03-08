Guide the user through first-time setup of Arbi Flow. Do this step-by-step — don't dump everything at once. Complete each step fully before moving to the next.

---

## Step 1 — System Check

Run these two commands to check for required system dependencies:

```bash
python3 --version
```

```bash
ffmpeg -version 2>&1 | head -1
```

**Python:** Must be 3.10 or higher. If missing or older:
- macOS: `brew install python@3.11` (requires Homebrew: https://brew.sh)
- Windows: Download from https://python.org/downloads — check "Add to PATH"
- Linux: `sudo apt install python3.11` (Ubuntu/Debian)

**ffmpeg:** Must be installed. If missing:
- macOS: `brew install ffmpeg`
- Windows: Download from https://ffmpeg.org/download.html and add to PATH
- Linux: `sudo apt install ffmpeg`

If either is missing, help the user install it and re-run the check before continuing.

---

## Step 2 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

Wait for it to complete. If there are errors, help debug them (common: wrong pip version — try `pip3` instead).

---

## Step 3 — API Keys

Tell the user: "You'll need 4 API keys. I'll walk you through each one. Each key requires a free account signup — I'll show you where to get each one."

Get each key one at a time in this order. For each key:
1. Show the signup URL and what it costs
2. Ask the user to sign up, get the key, and paste it here
3. Move to the next key only after they've provided it

**Key 1 — Gemini (Google AI)**
- URL: https://aistudio.google.com/apikey
- Cost: Free tier available; at ~$0.77/run, Gemini's share is under $0.06
- Used for: finding trending events, analyzing videos, generating character images, writing animation direction
- Ask: "Go to that link, sign in with your Google account, click 'Create API key', and paste it here."

**Key 2 — Serper**
- URL: https://serper.dev
- Cost: 2,500 free searches/month (plenty for casual use); paid after that
- Used for: finding the right video URL for each trending event
- Ask: "Sign up at serper.dev, go to your dashboard, copy the API key, and paste it here."

**Key 3 — fal.ai**
- URL: https://fal.ai/dashboard/keys
- Cost: ~$0.70 per video (this is the biggest cost — Kling 2.5 Turbo Pro at $0.07/s × 10s)
- Used for: generating the animated Arbi video
- Ask: "Sign up at fal.ai, go to the dashboard, create a key, and paste it here."

**Key 4 — ElevenLabs**
- URL: https://elevenlabs.io
- Cost: Free tier includes enough credits for ~50 runs/month
- Used for: generating Arbi's troll sounds
- Ask: "Sign up at elevenlabs.io, go to Profile → API Keys, create a key, and paste it here."

Once you have all 4 keys, write them to `.env` by running:

```bash
cp .env.example .env
```

Then open `.env` and fill in the values. You can do this by telling the user to open the `.env` file in their editor, or you can write the values directly if they've pasted all 4 keys.

---

## Step 4 — Validate

Run this to confirm the config loads correctly:

```bash
python3 -c "from config import load_config; cfg = load_config(); print('All keys loaded successfully!')"
```

If it prints "All keys loaded successfully!" — move on.

If it throws an error, show the user which key is missing and go back to Step 3 for that key.

---

## Step 5 — Ready

Tell the user:

"You're all set! Here's how to generate your first Arbi video:

- **`/video`** — Arbi auto-picks a trending event and generates a video (~5 min, ~$0.77)
- **`/video-pick`** — Scout finds 3 trending events, you choose which one
- **`/video-custom`** — You name a specific event for Arbi to re-enact

Just type one of those commands in the chat to get started."

Optionally ask if they want to run `/video` right now.
