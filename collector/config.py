"""Runtime configuration, read from environment variables (GitHub Actions secrets)."""
import os

# Postgres connection string for the Supabase project.
# Use the *session pooler* string from Supabase > Connect (IPv4-compatible, works from GitHub Actions).
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Gmail API (optional — the email step is skipped if these are missing)
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")
# Gmail search used to find newsletter issues. Narrow it with a label once one exists (e.g. "label:ds-index").
GMAIL_QUERY = os.environ.get("GMAIL_QUERY", "newer_than:3d -in:sent -in:chats")

USER_AGENT = os.environ.get(
    "COLLECTOR_USER_AGENT",
    "DSTopicIndexBot/0.1 (+https://github.com/NovaVolunteer/dscontentanalysis; academic research)",
)
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))

# Only fetch article pages for entries published within this many days (keeps first runs bounded).
MAX_ITEM_AGE_DAYS = int(os.environ.get("MAX_ITEM_AGE_DAYS", "14"))
# If the feed already carries at least this many words, skip fetching the page.
MIN_FEED_WORDS = int(os.environ.get("MIN_FEED_WORDS", "250"))
