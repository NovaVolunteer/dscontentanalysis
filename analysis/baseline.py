"""Baseline measurements run at the end of every collection.

This is a placeholder for the analytical plan. It records two simple, always-useful series in
public.analysis_results so there is something to chart from day one:

  daily_items_by_source  key=source_id, value_num=items published that day, value_json={words}
  daily_items_by_medium  key=medium,    value_num=items published that day

Both are recomputed for the trailing 7 days on every run (idempotent).
"""

WINDOW_DAYS = 7


def run(conn, run_id: int) -> None:
    conn.execute(
        """delete from public.analysis_results
           where analysis in ('daily_items_by_source','daily_items_by_medium')
             and period_start >= current_date - %s""",
        (WINDOW_DAYS,),
    )
    conn.execute(
        """insert into public.analysis_results (run_id, analysis, period_start, period_end, key, value_num, value_json)
           select %s, 'daily_items_by_source', d, d, i.source_id, count(*),
                  jsonb_build_object('words', coalesce(sum(t.word_count), 0))
           from (select *, published_at::date as d from public.items) i
           left join public.item_text t using (item_id)
           where i.d >= current_date - %s and i.d <= current_date
           group by d, i.source_id""",
        (run_id, WINDOW_DAYS),
    )
    conn.execute(
        """insert into public.analysis_results (run_id, analysis, period_start, period_end, key, value_num)
           select %s, 'daily_items_by_medium', i.published_at::date, i.published_at::date, s.medium, count(*)
           from public.items i join public.sources s using (source_id)
           where i.published_at::date >= current_date - %s and i.published_at::date <= current_date
           group by i.published_at::date, s.medium""",
        (run_id, WINDOW_DAYS),
    )
