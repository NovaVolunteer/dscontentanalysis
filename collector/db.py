"""Postgres (Supabase) reads and writes."""
import json

import psycopg
from psycopg.rows import dict_row

from .feeds import word_count
from .models import Item


def connect(dsn: str) -> psycopg.Connection:
    # prepare_threshold=None keeps it compatible with Supabase's pgbouncer/supavisor poolers
    return psycopg.connect(dsn, row_factory=dict_row, prepare_threshold=None, autocommit=False)


def active_sources(conn, priorities=None, source_ids=None) -> list:
    q = "select * from public.sources where active"
    args = []
    if priorities:
        q += " and mvp_priority = any(%s)"
        args.append(list(priorities))
    if source_ids:
        q += " and source_id = any(%s)"
        args.append(list(source_ids))
    q += " order by source_id"
    return conn.execute(q, args).fetchall()


def start_run(conn) -> int:
    run_id = conn.execute("insert into public.collection_runs default values returning run_id").fetchone()["run_id"]
    conn.commit()
    return run_id


def finish_run(conn, run_id, status, sources_polled, items_new, items_failed, notes):
    conn.execute(
        """update public.collection_runs
           set finished_at = now(), status = %s, sources_polled = %s, items_new = %s,
               items_failed = %s, notes = %s
           where run_id = %s""",
        (status, sources_polled, items_new, items_failed, notes, run_id),
    )
    conn.commit()


def mark_source(conn, source_id, ok, resolved_feed_url=None):
    if ok:
        conn.execute(
            """update public.sources set last_polled_at = now(), last_success_at = now(),
                   consecutive_failures = 0, feed_verified = true,
                   feed_url = coalesce(%s, feed_url), updated_at = now()
               where source_id = %s""",
            (resolved_feed_url, source_id),
        )
    else:
        conn.execute(
            """update public.sources set last_polled_at = now(),
                   consecutive_failures = consecutive_failures + 1, updated_at = now()
               where source_id = %s""",
            (source_id,),
        )


def existing_external_ids(conn, source_id) -> set:
    rows = conn.execute("select external_id from public.items where source_id = %s", (source_id,)).fetchall()
    return {r["external_id"] for r in rows}


def _clean(v):
    return v.replace("\x00", "") if isinstance(v, str) else v


def insert_item(conn, item: Item, run_id: int) -> bool:
    """Insert one item + its text. Returns False if it already existed (by source/external_id or url)."""
    row = conn.execute(
        """insert into public.items
             (source_id, external_id, url, title, author, published_at, run_id, content_type, summary, raw_payload)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict do nothing
           returning item_id""",
        (
            item.source_id, item.external_id, item.url, _clean(item.title), _clean(item.author), item.published_at,
            run_id, item.content_type, _clean(item.summary), json.dumps(item.raw_payload, default=str).replace("\\u0000", ""),
        ),
    ).fetchone()
    if not row:
        return False
    conn.execute(
        """insert into public.item_text
             (item_id, text_source, body_text, word_count, extraction_status, extraction_error, extracted_at)
           values (%s,%s,%s,%s,%s,%s, now())""",
        (
            row["item_id"], item.text_source, _clean(item.body_text), word_count(item.body_text),
            item.extraction_status, item.extraction_error,
        ),
    )
    return True
