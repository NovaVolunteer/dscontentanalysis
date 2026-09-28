"""Upsert the source registry CSV into public.sources.

    DATABASE_URL=... python scripts/load_sources.py data/ds_source_registry_v1.csv

Adds new sources and updates descriptive fields of existing ones. It never overwrites a
feed_url the collector has already resolved/verified, and never touches run-state columns.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collector import db  # noqa: E402


def ingest_method(row: dict) -> str:
    if row["medium"] == "podcast":
        return "podcast_rss"
    if row["medium"] == "youtube":
        return "youtube_rss"
    return "rss" if row["feed_url"].startswith("http") else "email"


def main(path: str) -> None:
    rows = list(csv.DictReader(open(path, newline="")))
    conn = db.connect(os.environ["DATABASE_URL"])
    for r in rows:
        feed = r["feed_url"] if r["feed_url"].startswith("http") else None
        conn.execute(
            """insert into public.sources (source_id, name, medium, platform, primary_url, feed_url,
                   ingest_method, signup_method, focus, scope, audience_reported, audience_source,
                   cadence, mvp_priority, status_notes)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (source_id) do update set
                   name = excluded.name, medium = excluded.medium, platform = excluded.platform,
                   primary_url = excluded.primary_url,
                   feed_url = case when public.sources.feed_verified then public.sources.feed_url
                                   else coalesce(excluded.feed_url, public.sources.feed_url) end,
                   ingest_method = excluded.ingest_method, signup_method = excluded.signup_method,
                   focus = excluded.focus, scope = excluded.scope,
                   audience_reported = excluded.audience_reported, audience_source = excluded.audience_source,
                   cadence = excluded.cadence, mvp_priority = excluded.mvp_priority,
                   status_notes = excluded.status_notes, updated_at = now()""",
            (
                r["source_id"], r["name"], r["medium"], r["platform"] or None, r["primary_url"], feed,
                ingest_method(r), r["signup_method"] or None, r["focus"] or None, r["scope"] or None,
                r["audience_reported"] or None, r["audience_source"] or None, r["cadence"] or None,
                r["mvp_priority"] or None, r["status_notes"] or None,
            ),
        )
    conn.commit()
    print(f"upserted {len(rows)} sources")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/ds_source_registry_v1.csv")
