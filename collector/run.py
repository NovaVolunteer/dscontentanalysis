"""Daily collection run.

    python -m collector.run                  # all active sources
    python -m collector.run --priority P1    # just P1 sources
    python -m collector.run --source NL004 --source YT001
    python -m collector.run --skip-email
"""
import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, db, extract, feeds, gmail_source, http
from .models import SourceResult

log = logging.getLogger("collector")


def collect_source(src: dict, known_ids: set) -> SourceResult:
    sid, method = src["source_id"], src["ingest_method"]
    feed_url = src["feed_url"]
    resolved = None
    try:
        if not feed_url:
            if method == "youtube_rss":
                feed_url = resolved = feeds.resolve_youtube_feed(src["primary_url"])
            elif method == "podcast_rss":
                feed_url = resolved = feeds.resolve_podcast_feed(src["name"])
            else:
                raise ValueError("no feed_url")
        content = http.get(feed_url).content
        items = [i for i in feeds.parse_feed(sid, method, content) if i.external_id not in known_ids]
        for it in items:
            extract.finalize_text(it)
            if it.content_type == "article" and it.text_source == "html_extract":
                time.sleep(0.5)  # be polite to the same host
        return SourceResult(sid, True, items, resolved_feed_url=resolved)
    except Exception as ex:
        return SourceResult(sid, False, error=f"{type(ex).__name__}: {ex}"[:300], resolved_feed_url=resolved)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--priority", action="append", choices=["P1", "P2", "P3"])
    ap.add_argument("--source", action="append")
    ap.add_argument("--skip-email", action="store_true")
    ap.add_argument("--skip-analysis", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not config.DATABASE_URL:
        log.error("DATABASE_URL is not set")
        return 2

    conn = db.connect(config.DATABASE_URL)
    run_id = db.start_run(conn)
    sources = db.active_sources(conn, args.priority, args.source)
    feed_sources = [s for s in sources if s["ingest_method"] != "email"]
    email_sources = [s for s in sources if s["ingest_method"] == "email"]
    log.info("run %s: %d feed sources, %d email sources", run_id, len(feed_sources), len(email_sources))

    known = {s["source_id"]: db.existing_external_ids(conn, s["source_id"]) for s in sources}
    conn.commit()

    new_items, failed_items, notes = 0, 0, []
    failures = []

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futs = {pool.submit(collect_source, s, known[s["source_id"]]): s for s in feed_sources}
        for fut in as_completed(futs):
            res = fut.result()
            db.mark_source(conn, res.source_id, res.ok, res.resolved_feed_url)
            if not res.ok:
                failures.append(f"{res.source_id}: {res.error}")
                log.warning("FAIL %s — %s", res.source_id, res.error)
                conn.commit()
                continue
            added = 0
            for it in res.items:
                if db.insert_item(conn, it, run_id):
                    added += 1
                    failed_items += it.extraction_status == "failed"
            conn.commit()
            new_items += added
            log.info("ok   %s — %d new", res.source_id, added)

    if email_sources and not args.skip_email:
        if gmail_source.enabled():
            try:
                pairs = [(s["source_id"], s["email_sender"], s["primary_url"]) for s in email_sources]
                items, unmatched = gmail_source.collect(pairs)
                matched_sids = set()
                for it in items:
                    it.extraction_status = "ok" if it.body_text else "failed"
                    if db.insert_item(conn, it, run_id):
                        new_items += 1
                    matched_sids.add(it.source_id)
                for sid in matched_sids:
                    db.mark_source(conn, sid, True)
                conn.commit()
                log.info("gmail — %d issues matched, %d unmatched senders", len(items), len(unmatched))
                if unmatched:
                    notes.append("unmatched email senders: " + ", ".join(unmatched[:30]))
            except Exception as ex:
                conn.rollback()
                failures.append(f"gmail: {type(ex).__name__}: {ex}"[:300])
                log.warning("gmail step failed: %s", ex)
        else:
            notes.append("gmail step skipped (credentials not configured)")

    if not args.skip_analysis:
        try:
            from analysis import baseline
            baseline.run(conn, run_id)
            conn.commit()
        except Exception as ex:
            conn.rollback()
            failures.append(f"analysis: {type(ex).__name__}: {ex}"[:300])
            log.warning("analysis step failed: %s", ex)

    status = "success" if not failures else ("partial" if len(failures) < max(1, len(feed_sources)) else "failed")
    notes = "; ".join(notes + (["failures: " + " | ".join(failures)] if failures else []))
    db.finish_run(conn, run_id, status, len(feed_sources) + len(email_sources), new_items, failed_items, notes[:8000])
    log.info("run %s finished: %s, %d new items, %d source failures", run_id, status, new_items, len(failures))
    conn.close()
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
