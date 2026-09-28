"""Full-text extraction for items whose feed only carries a teaser."""
from datetime import datetime, timedelta, timezone

import trafilatura

from . import config, http
from .feeds import word_count
from .models import Item


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
        item.body_text = item.body_text or item.summary
        item.text_source = item.text_source or "description_only"
        item.extraction_status = "ok" if item.body_text else "skipped"
        return
    if needs_page_fetch(item):
        try:
            page = http.get(item.url).text
            text = trafilatura.extract(page, include_comments=False, include_tables=False, favor_recall=True)
            if text and word_count(text) > word_count(item.body_text):
                item.body_text = text
                item.text_source = "html_extract"
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
