"""Collect newsletter issues from the project Gmail inbox via the Gmail REST API."""
import base64
import email.utils
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from . import config, http
from .feeds import html_to_text
from .models import Item

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def enabled() -> bool:
    return all([config.GMAIL_CLIENT_ID, config.GMAIL_CLIENT_SECRET, config.GMAIL_REFRESH_TOKEN])


def _access_token() -> str:
    r = http.session().post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
            "refresh_token": config.GMAIL_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _bodies(payload: dict, out: dict) -> None:
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if data and mime in ("text/plain", "text/html"):
        out.setdefault(mime, _b64(data))
    for p in payload.get("parts", []) or []:
        _bodies(p, out)


def base_domain(host: str) -> str:
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def match_source(sender_addr: str, email_sources: list) -> Optional[str]:
    """email_sources: [(source_id, email_sender, primary_url)]. Exact sender first, then domain."""
    sender_addr = sender_addr.lower()
    for sid, sender, _ in email_sources:
        if sender and sender.lower() == sender_addr:
            return sid
    dom = base_domain(sender_addr.split("@")[-1])
    for sid, _, url in email_sources:
        if base_domain(urlparse(url).hostname or "") == dom:
            return sid
    return None


def collect(email_sources: list) -> tuple:
    """Returns (items, unmatched_senders)."""
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}"}
    ids, page = [], None
    while True:
        params = {"q": config.GMAIL_QUERY, "maxResults": 100}
        if page:
            params["pageToken"] = page
        r = http.get(f"{API}/messages", headers=headers, params=params).json()
        ids += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page or len(ids) >= 500:
            break

    items, unmatched = [], set()
    for mid in ids:
        msg = http.get(f"{API}/messages/{mid}", headers=headers, params={"format": "full"}).json()
        hdrs = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        name, addr = email.utils.parseaddr(hdrs.get("from", ""))
        sid = match_source(addr, email_sources)
        if not sid:
            unmatched.add(addr)
            continue
        bodies = {}
        _bodies(msg["payload"], bodies)
        text = html_to_text(bodies["text/html"]) if "text/html" in bodies else bodies.get("text/plain", "")
        published = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc)
        items.append(
            Item(
                source_id=sid,
                external_id=f"gmail:{mid}",
                title=(hdrs.get("subject") or "(no subject)")[:1000],
                url=None,
                author=name or addr,
                published_at=published,
                content_type="newsletter_issue",
                summary=msg.get("snippet"),
                raw_payload={"from": addr, "list_id": hdrs.get("list-id"), "gmail_thread": msg.get("threadId")},
                body_text=text or None,
                text_source="email_body" if text else None,
            )
        )
    return items, sorted(unmatched)
