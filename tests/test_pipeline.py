"""End-to-end run against a scratch Postgres with all network calls mocked.

    TEST_DATABASE_URL=postgresql://... pytest tests/test_pipeline.py

The database must already have the schema and the sources loaded. Do NOT point this at production.
"""
import json
import os
from pathlib import Path

import pytest

from collector import config, db, extract, http, run

FIX = Path(__file__).parent / "fixtures"
DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")

ARTICLE = "<html><body><article><h1>GBM</h1>" + "<p>" + " ".join(["boosting"] * 600) + "</p></article></body></html>"


class Resp:
    status_code = 200

    def __init__(self, body):
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode()

    def json(self):
        return json.loads(self.text)


def fake_get(url, **kw):
    if url == "https://datascienceweekly.substack.com/feed":
        return Resp((FIX / "substack.xml").read_bytes())
    if url == "https://www.youtube.com/@statquest":
        return Resp('<html>..."channelId":"UCtYLUTtgS3k1Fg4y5tAhLbw"...</html>')
    if "feeds/videos.xml?channel_id=UCtYLUTtgS3k1Fg4y5tAhLbw" in url:
        return Resp((FIX / "youtube.xml").read_bytes())
    if url == "https://itunes.apple.com/search":
        return Resp(json.dumps({"results": [
            {"collectionName": "Something Else", "feedUrl": "https://x/else.xml"},
            {"collectionName": "Super Data Science: ML & AI Podcast with Jon Krohn", "feedUrl": "https://feeds.example.com/sds.xml"},
        ]}))
    if url == "https://feeds.example.com/sds.xml":
        return Resp((FIX / "podcast.xml").read_bytes())
    if url == "https://example.substack.com/p/gbm":
        return Resp(ARTICLE)
    if url == "https://practicalai.fm/broken":
        raise RuntimeError("boom")
    raise AssertionError(f"unexpected URL {url}")


def test_end_to_end(monkeypatch):
    monkeypatch.setattr(http, "get", fake_get)
    monkeypatch.setattr(extract, "allowed_by_robots", lambda url: True)
    monkeypatch.setattr(config, "DATABASE_URL", DSN)
    conn = db.connect(DSN)
    conn.execute("update sources set feed_url = 'https://practicalai.fm/broken' where source_id = 'PC004'")
    conn.commit()

    ids = ["--source", "NL004", "--source", "YT001", "--source", "PC001", "--source", "PC004", "--skip-email"]
    assert run.main(ids) == 0

    items = conn.execute("select source_id, content_type, title from items order by source_id, title").fetchall()
    assert [i["source_id"] for i in items] == ["NL004", "NL004", "PC001", "YT001"]

    gbm = conn.execute(
        "select t.* from items i join item_text t using (item_id) where i.url = 'https://example.substack.com/p/gbm'"
    ).fetchone()
    assert gbm["text_source"] == "html_extract" and gbm["word_count"] >= 600

    yt = conn.execute("select feed_url, feed_verified from sources where source_id = 'YT001'").fetchone()
    assert yt["feed_verified"] and yt["feed_url"].endswith("UCtYLUTtgS3k1Fg4y5tAhLbw")
    pc = conn.execute("select feed_url from sources where source_id = 'PC001'").fetchone()
    assert pc["feed_url"] == "https://feeds.example.com/sds.xml"
    bad = conn.execute("select consecutive_failures from sources where source_id = 'PC004'").fetchone()
    assert bad["consecutive_failures"] == 1

    r = conn.execute("select * from collection_runs order by run_id desc limit 1").fetchone()
    assert r["status"] == "partial" and r["items_new"] == 4 and "PC004" in r["notes"]

    # second run: nothing new, no duplicates
    assert run.main(ids) == 0
    assert conn.execute("select count(*) as n from items").fetchone()["n"] == 4
    assert conn.execute("select count(*) as n from analysis_results").fetchone()["n"] > 0
    conn.close()
