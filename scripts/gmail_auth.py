"""One-time helper: get a Gmail refresh token for the project inbox.

Run this on your own computer (not in GitHub Actions):

    pip install google-auth-oauthlib
    python scripts/gmail_auth.py path/to/client_secret.json

A browser window opens — sign in with the PROJECT Gmail account and approve read-only access.
The script prints GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN; paste those
into the repo's GitHub Actions secrets. Nothing is written to disk.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main(path: str) -> None:
    flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    cfg = json.load(open(path))
    cfg = cfg.get("installed") or cfg.get("web")
    print("\nAdd these as GitHub Actions secrets:\n")
    print("GMAIL_CLIENT_ID     =", cfg["client_id"])
    print("GMAIL_CLIENT_SECRET =", cfg["client_secret"])
    print("GMAIL_REFRESH_TOKEN =", creds.refresh_token)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
