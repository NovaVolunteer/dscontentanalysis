-- DS Topic Index — core schema v1 (Supabase / Postgres 17)
-- Scope: source registry, collected items, extracted text, run log, analysis placeholder.

create extension if not exists vector with schema extensions;    -- pgvector for embeddings (later)
create extension if not exists pg_trgm with schema extensions;    -- fuzzy title matching / dedup

-- 1. Source registry (loaded from ds_source_registry_v1.csv)
create table public.sources (
  source_id        text primary key,               -- e.g. NL001
  name             text not null,
  medium           text not null check (medium in ('newsletter','newsletter+podcast','blog','medium','podcast','youtube')),
  platform         text,
  primary_url      text not null,
  feed_url         text,
  feed_verified    boolean not null default false,
  ingest_method    text not null default 'rss' check (ingest_method in ('rss','email','youtube_rss','podcast_rss','manual')),
  email_sender     text,                            -- From: address for email-only newsletters
  signup_method    text,
  focus            text,
  scope            text,                            -- core / adjacent-AI / adjacent-dev / adjacent-math
  audience_reported text,
  audience_source  text,
  cadence          text,
  mvp_priority     text check (mvp_priority in ('P1','P2','P3')),
  active           boolean not null default true,
  status_notes     text,
  last_polled_at   timestamptz,
  last_success_at  timestamptz,
  consecutive_failures int not null default 0,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- 2. Daily collection runs
create table public.collection_runs (
  run_id        bigint generated always as identity primary key,
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  status        text not null default 'running' check (status in ('running','success','partial','failed')),
  sources_polled int default 0,
  items_new     int default 0,
  items_failed  int default 0,
  notes         text
);

-- 3. One row per piece of content (article, issue, episode, video)
create table public.items (
  item_id        bigint generated always as identity primary key,
  source_id      text not null references public.sources(source_id),
  external_id    text,                               -- feed guid / Gmail message id / YouTube video id
  url            text,
  title          text not null,
  author         text,
  published_at   timestamptz,
  collected_at   timestamptz not null default now(),
  run_id         bigint references public.collection_runs(run_id),
  content_type   text check (content_type in ('article','newsletter_issue','podcast_episode','video')),
  summary        text,                               -- feed-provided description
  raw_payload    jsonb,                              -- original feed entry / email metadata
  unique (source_id, external_id),
  unique (url)
);

-- 4. Extracted full text (kept separate so items stays light)
create table public.item_text (
  item_id          bigint primary key references public.items(item_id) on delete cascade,
  text_source      text check (text_source in ('feed_full','html_extract','email_body','transcript','description_only')),
  body_text        text,
  word_count       int,
  language         text,
  extraction_status text not null default 'pending' check (extraction_status in ('pending','ok','failed','skipped')),
  extraction_error text,
  extracted_at     timestamptz
);

-- 5. Embeddings (populated once the analysis plan picks a model)
create table public.item_embeddings (
  item_id    bigint references public.items(item_id) on delete cascade,
  model      text not null,
  chunk_no   int not null default 0,
  embedding  extensions.vector(1536),
  created_at timestamptz not null default now(),
  primary key (item_id, model, chunk_no)
);

-- 6. Generic analysis output (shape finalized by the analytical plan)
create table public.analysis_results (
  result_id    bigint generated always as identity primary key,
  run_id       bigint references public.collection_runs(run_id),
  analysis     text not null,              -- e.g. 'topic_tags', 'concept_counts_daily'
  item_id      bigint references public.items(item_id) on delete cascade,
  period_start date,
  period_end   date,
  key          text,                       -- e.g. concept / topic label
  value_num    double precision,
  value_json   jsonb,
  created_at   timestamptz not null default now()
);

-- Indexes
create index items_published_idx on public.items (published_at desc);
create index items_source_idx    on public.items (source_id, published_at desc);
create index items_title_trgm    on public.items using gin (title extensions.gin_trgm_ops);
create index item_text_status_idx on public.item_text (extraction_status);
create index analysis_lookup_idx on public.analysis_results (analysis, period_start, key);
create index items_run_idx       on public.items (run_id);
create index analysis_run_idx    on public.analysis_results (run_id);
create index analysis_item_idx   on public.analysis_results (item_id);

-- Row Level Security: on everywhere, no public policies.
-- The daily job connects with the service-role key (bypasses RLS); nothing is exposed via the anon key.
alter table public.sources          enable row level security;
alter table public.collection_runs  enable row level security;
alter table public.items            enable row level security;
alter table public.item_text        enable row level security;
alter table public.item_embeddings  enable row level security;
alter table public.analysis_results enable row level security;
