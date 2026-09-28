from pathlib import Path

from collector import extract, feeds, gmail_source

FIX = Path(__file__).parent / "fixtures"


def test_substack_full_content():
    items = feeds.parse_feed("NL004", "rss", (FIX / "substack.xml").read_bytes())
    assert len(items) == 2
    a = items[0]
    assert a.external_id == "https://example.substack.com/p/gbm"
    assert a.author == "Jane Analyst"
    assert a.text_source == "feed_full"
    assert "XGBoost & LightGBM" in a.body_text
    assert "bad()" not in a.body_text
    assert a.raw_payload["tags"] == ["machine learning"]
    assert a.published_at.year == 2026


def test_old_teaser_falls_back_to_summary_without_fetch():
    items = feeds.parse_feed("NL004", "rss", (FIX / "substack.xml").read_bytes())
    t = items[1]
    assert not extract.needs_page_fetch(t)  # older than MAX_ITEM_AGE_DAYS
    extract.finalize_text(t)
    assert t.text_source == "description_only"
    assert t.body_text == "Only a summary here."


def test_youtube_feed():
    (v,) = feeds.parse_feed("YT001", "youtube_rss", (FIX / "youtube.xml").read_bytes())
    assert v.content_type == "video"
    assert v.url == "https://www.youtube.com/watch?v=abc123XYZ00"
    extract.finalize_text(v)
    assert v.text_source == "description_only"
    assert "positional encoding" in v.body_text


def test_podcast_feed():
    (e,) = feeds.parse_feed("PC001", "podcast_rss", (FIX / "podcast.xml").read_bytes())
    assert e.content_type == "podcast_episode"
    assert e.external_id == "ep-900"
    assert e.url == "https://cdn.example.com/ep900.mp3"
    assert e.raw_payload["duration"] == "01:02:03"


def test_youtube_channel_id_from_url():
    url = "https://www.youtube.com/channel/UCtYLUTtgS3k1Fg4y5tAhLbw"
    assert feeds.resolve_youtube_feed(url).endswith("channel_id=UCtYLUTtgS3k1Fg4y5tAhLbw")


def test_gmail_sender_matching():
    srcs = [
        ("NL001", None, "https://tldr.tech/data"),
        ("NL009", "hi@dataelixir.com", "https://dataelixir.com"),
        ("NL003", None, "https://www.deeplearning.ai/the-batch/"),
    ]
    assert gmail_source.match_source("hi@dataelixir.com", srcs) == "NL009"
    assert gmail_source.match_source("thebatch@deeplearning.ai", srcs) == "NL003"
    assert gmail_source.match_source("dan@tldrnewsletter.com", srcs) is None


def test_gmail_substack_and_platform_senders():
    srcs = [
        ("NL004", None, "https://datascienceweekly.substack.com"),
        ("NL019", None, "https://seattledataguy.substack.com"),
        ("NL025", None, "https://www.therundown.ai"),
    ]
    assert gmail_source.match_source("seattledataguy@substack.com", srcs) == "NL019"
    assert gmail_source.match_source("datascienceweekly@substack.com", srcs) == "NL004"
    assert gmail_source.match_source("someoneelse@substack.com", srcs) is None
    assert gmail_source.match_source("news@medium.com", srcs) is None


def test_podcast_text_labelled_as_description():
    (e,) = feeds.parse_feed("PC001", "podcast_rss", (FIX / "podcast.xml").read_bytes())
    e.body_text, e.text_source = "Show notes " * 50, "feed_full"
    extract.finalize_text(e)
    assert e.text_source == "description_only"


def test_blocked_page_records_error(monkeypatch):
    from datetime import datetime, timezone
    from collector.models import Item

    class R:
        status_code = 202
        text = "<html>challenge</html>"

    monkeypatch.setattr(extract, "allowed_by_robots", lambda u: True)
    monkeypatch.setattr(extract.http, "get", lambda u, **k: R())
    it = Item("BL001", "x", "Title", url="https://example.com/a", summary="teaser text",
              published_at=datetime.now(timezone.utc))
    extract.finalize_text(it)
    assert it.text_source == "description_only" and "202" in it.extraction_error
