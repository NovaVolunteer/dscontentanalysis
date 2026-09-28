from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Item:
    source_id: str
    external_id: str
    title: str
    url: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    content_type: str = "article"
    summary: Optional[str] = None
    raw_payload: dict = field(default_factory=dict)
    # text
    body_text: Optional[str] = None
    text_source: Optional[str] = None
    extraction_status: str = "pending"
    extraction_error: Optional[str] = None


@dataclass
class SourceResult:
    source_id: str
    ok: bool
    items: list = field(default_factory=list)
    error: Optional[str] = None
    resolved_feed_url: Optional[str] = None
