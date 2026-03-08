#!/usr/bin/env python3
"""One-time OAuth setup for YouTube Data API v3.

This script:
1. Opens a browser for you to authorize Arbi to upload to your YouTube channel
2. Saves refresh token to youtube_token.json for future uploads
3. Only needs to be run once (unless you revoke access)

Create OAuth 2.0 Client ID (one-time):
1. Open https://console.cloud.google.com/
2. Create/select project: top bar "Select a project" → New Project (e.g. "Arbi Upload") or pick existing
3. OAuth consent screen (required before Client ID):
   - APIs & Services → OAuth consent screen
   - User type: External → Create (or use existing)
   - App name: e.g. "Arbi Upload", support email: your email → Save and Continue
   - Scopes: Add or Remove Scopes → add "YouTube Data API v3" → .../auth/youtube.force-ssl → Update → Save
   - Test users: if in Testing, add your Google account → Save and Continue
4. Enable YouTube Data API v3:
   - APIs & Services → Library → search "YouTube Data API v3" → Enable
5. Create Client ID:
   - APIs & Services → Credentials → + Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Name: e.g. "Arbi Desktop"
   - Create → Download JSON
6. Save the downloaded file as client_secret.json in this project directory
7. Run: python3 setup_youtube_auth.py
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError

# youtube.force-ssl: upload + add to playlists (Arbi category)
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_FILE = "youtube_token.json"
CLIENT_SECRET_FILE = "client_secret.json"


def setup_youtube_oauth():
    """Run OAuth flow and save credentials."""

    # Check if client_secret.json exists
    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"❌ Error: {CLIENT_SECRET_FILE} not found!")
        print("\nSetup instructions:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project (or use existing)")
        print('3. Enable "YouTube Data API v3"')
        print('4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"')
        print('5. Application type: "Desktop app"')
        print(f"6. Download JSON and save as {CLIENT_SECRET_FILE}")
        print("7. Run this script again")
        sys.exit(1)

    creds = None

    # Check if we already have a token
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"⚠️  Existing token is invalid: {e}")
            creds = None

    # If credentials are invalid or don't exist, run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("🔄 Refreshing expired token...")
                creds.refresh(Request())
            except RefreshError:
                # Old token has wrong scope (e.g. youtube.upload vs youtube.force-ssl) — re-auth
                print("⚠️  Token scope changed; re-authorization needed.")
                os.remove(TOKEN_FILE)
                creds = None

        if not creds or not creds.valid:
            print("🔐 Starting OAuth flow...")
            print("→ A browser window will open")
            print("→ Sign in with your YouTube account")
            print("→ Grant Arbi permission to upload videos")

            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the credentials for future runs
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

        print(f"✅ Authentication successful!")
        print(f"✅ Refresh token saved to {TOKEN_FILE}")
        print("\nYou can now run the video pipeline with YouTube upload enabled.")
        print("Set YOUTUBE_UPLOAD_ENABLED=true in your .env file.")
        print("Set YOUTUBE_ARBI_PLAYLIST_ID to add every video to your Arbi playlist.")
    else:
        print(f"✅ Valid credentials already exist in {TOKEN_FILE}")
        print("No action needed!")


if __name__ == "__main__":
    setup_youtube_oauth()
