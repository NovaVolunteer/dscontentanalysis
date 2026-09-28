"""Feed resolution (YouTube channel -> RSS, podcast name -> RSS) and feed parsing."""
import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser

from . import http
from .models import Item

YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
_CHANNEL_ID_PATTERNS = [
    re.compile(r'"channelId":"(UC[0-9A-Za-z_-]{22})"'),
    re.compile(r'"externalId":"(UC[0-9A-Za-z_-]{22})"'),
    re.compile(r'youtube\.com/channel/(UC[0-9A-Za-z_-]{22})'),
]


def resolve_youtube_feed(channel_url: str) -> str:
    """Turn https://www.youtube.com/@handle into its public RSS feed URL."""
    m = re.search(r"/channel/(UC[0-9A-Za-z_-]{22})", channel_url)
    if m:
        return YT_FEED.format(m.group(1))
    page = http.get(channel_url, headers={"Accept-Language": "en-US,en;q=0.8"}).text
    for pat in _CHANNEL_ID_PATTERNS:
        m = pat.search(page)
        if m:
            return YT_FEED.format(m.group(1))
    raise ValueError(f"could not find channel id on {channel_url}")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split("(")[0].strip()


def resolve_podcast_feed(name: str) -> str:
    """Look the show up in the iTunes Search API (no key needed) and return its RSS feed URL."""
    term = re.sub(r"\(.*?\)", "", name).strip()
    r = http.get(
        "https://itunes.apple.com/search",
        params={"term": term, "media": "podcast", "entity": "podcast", "limit": 10},
    ).json()
    results = [x for x in r.get("results", []) if x.get("feedUrl")]
    if not results:
        raise ValueError(f"no podcast feed found for '{term}'")
    want = set(_norm(term).split())
    # pick the result whose title shares the most words with the requested name
    best = max(results, key=lambda x: len(want & set(_norm(x.get("collectionName", "")).split())))
    overlap = len(want & set(_norm(best.get("collectionName", "")).split()))
    if overlap < max(1, len(want) // 2):
        raise ValueError(f"no confident podcast match for '{term}' (best: {best.get('collectionName')})")
    return best["feedUrl"]


def _dt(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>", "\n", s)
    s = html.unescape(_TAG_RE.sub(" ", s))
    lines = [_WS_RE.sub(" ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def word_count(s: Optional[str]) -> int:
    return len(s.split()) if s else 0


CONTENT_TYPE = {
    "podcast_rss": "podcast_episode",
    "youtube_rss": "video",
    "rss": "article",
}


def parse_feed(source_id: str, ingest_method: str, content: bytes) -> list:
    fp = feedparser.parse(content)
    if fp.bozo and not fp.entries:
        raise ValueError(f"unparseable feed: {fp.bozo_exception}")
    items = []
    for e in fp.entries:
        link = e.get("link")
        # podcasts: prefer the episode page; fall back to the audio enclosure
        enclosure = next((l.get("href") for l in e.get("links", []) if l.get("rel") == "enclosure"), None)
        ext_id = e.get("id") or e.get("guid") or link or enclosure
        if not ext_id:
            ext_id = hashlib.sha1((e.get("title", "") + str(e.get("published", ""))).encode()).hexdigest()
        full_html = ""
        if e.get("content"):
            full_html = max((c.get("value", "") for c in e.content), key=len)
        summary_html = e.get("summary", "")
        if ingest_method == "youtube_rss":
            summary_html = (e.get("media_description") or summary_html)
        item = Item(
            source_id=source_id,
            external_id=str(ext_id)[:1000],
            title=(e.get("title") or "(untitled)").strip()[:1000],
            url=link or enclosure,
            author=e.get("author"),
            published_at=_dt(e),
            content_type=CONTENT_TYPE.get(ingest_method, "article"),
            summary=html_to_text(summary_html)[:5000] or None,
            raw_payload={
                "feed_title": fp.feed.get("title"),
                "tags": [t.get("term") for t in e.get("tags", []) if t.get("term")],
                "enclosure": enclosure,
                "duration": e.get("itunes_duration"),
            },
        )
        full_text = html_to_text(full_html)
        if full_text:
            item.body_text = full_text
            item.text_source = "feed_full"
        items.append(item)
    return items
