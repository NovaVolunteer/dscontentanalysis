"""Full-text extraction for items whose feed only carries a teaser."""
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import trafilatura

from . import config, http
from .feeds import word_count
from .models import Item

_robots: dict = {}
_robots_lock = threading.Lock()


def allowed_by_robots(url: str) -> bool:
    """Respect robots.txt. If robots.txt can't be read cleanly (blocked, challenge page), don't fetch."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    with _robots_lock:
        rp = _robots.get(base)
        if rp is None:
            rp = RobotFileParser()
            try:
                r = http.session().get(base + "/robots.txt", timeout=config.HTTP_TIMEOUT)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif r.status_code == 404:
                    rp.allow_all = True
                else:  # 401/403/202 challenge etc. -> treat as disallowed
                    rp.disallow_all = True
            except Exception:
                rp.disallow_all = True
            _robots[base] = rp
    return rp.can_fetch(config.USER_AGENT, url)


def needs_page_fetch(item: Item) -> bool:
    if item.content_type in ("podcast_episode", "video"):
        return False  # transcripts are a later pipeline stage
    if not item.url or not item.url.startswith("http"):
        return False
    if item.published_at and item.published_at < datetime.now(timezone.utc) - timedelta(days=config.MAX_ITEM_AGE_DAYS):
        return False
    return word_count(item.body_text) < config.MIN_FEED_WORDS


def finalize_text(item: Item) -> None:
    """Fill body_text / text_source / extraction_status for one item."""
    if item.content_type in ("podcast_episode", "video"):
        # show notes / video descriptions, whether they came from content:encoded or the summary
        item.body_text = item.body_text or item.summary
        item.text_source = "description_only"
        item.extraction_status = "ok" if item.body_text else "skipped"
        return
    if needs_page_fetch(item):
        try:
            if not allowed_by_robots(item.url):
                item.extraction_error = "page fetch skipped: disallowed or unreadable robots.txt"
            else:
                r = http.get(item.url)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code} (likely bot challenge)")
                text = trafilatura.extract(r.text, include_comments=False, include_tables=False, favor_recall=True)
                if text and word_count(text) > word_count(item.body_text):
                    item.body_text = text
                    item.text_source = "html_extract"
                else:
                    item.extraction_error = "page fetched but no article text extracted"
        except Exception as ex:  # keep whatever the feed gave us
            item.extraction_error = f"{type(ex).__name__}: {ex}"[:500]
    if item.body_text:
        item.text_source = item.text_source or "feed_full"
        item.extraction_status = "ok"
    elif item.summary:
        item.body_text = item.summary
        item.text_source = "description_only"
        item.extraction_status = "ok"
    else:
        item.extraction_status = "failed"
