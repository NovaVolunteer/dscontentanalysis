# dscontentanalysis — Data Science Topic Index

Every morning, a GitHub Actions job collects new data science content from about 60 sources and stores it in Supabase (Postgres). The sources are newsletters, Substack, Medium, blogs, podcasts and YouTube. The job saves the full text of each item it can, then runs a set of analytical measurements on it.

```
sources (registry) ──► collector ──► items + item_text ──► analysis ──► analysis_results
   RSS / Substack / Medium ─┐
   YouTube channel feeds ───┤  (feed first; article page fetched with trafilatura if the feed is a teaser)
   Podcast feeds (iTunes) ──┤
   Gmail newsletters ───────┘
```

## Repo layout

| Path | What it is |
|---|---|
| `collector/` | The daily collector (`python -m collector.run`) |
| `analysis/baseline.py` | Placeholder measurements (daily item counts by source and medium). The analytical plan replaces or extends this. |
| `db/migrations/001_core_schema.sql` | Supabase schema (already applied to the `ds-topic-index` project) |
| `data/ds_source_registry_v1.csv` | Source registry. Load changes with `scripts/load_sources.py`. |
| `scripts/gmail_auth.py` | One-time helper that gets a Gmail refresh token |
| `.github/workflows/daily-collect.yml` | Runs every day at 10:15 UTC (6:15 AM ET in summer), and can also be run manually |

## Tables (Supabase project `ds-topic-index`)

- **`sources`**: the registry, how each source is collected (`ingest_method`), and its health (`last_success_at`, `consecutive_failures`, `feed_verified`). The collector resolves YouTube and podcast feed URLs on its first successful run and saves them back here.
- **`collection_runs`**: one row per run, with its status, new-item count and any failures (in `notes`).
- **`items`**: one row per article, issue, episode or video. Items are unique on `(source_id, external_id)` and on `url`.
- **`item_text`**: the full text, where it came from (`feed_full`, `html_extract`, `email_body`, `description_only`) and its word count.
- **`item_embeddings`** / **`analysis_results`**: storage for the analysis stage.

RLS is enabled on every table and there are no policies, so the anon key can't read anything. The collector connects directly with the database password.

## One-time setup

### 1. Database secret (required)

1. In Supabase, open **ds-topic-index → Connect → Session pooler** and copy the URI. It looks like `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-...pooler.supabase.com:5432/postgres`.
2. Put the database password into the URI. If you don't know the password, reset it under **Project Settings → Database**.
3. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**. Name it `DATABASE_URL` and paste the URI.

Use the session pooler, not the "direct connection". The direct connection only works over IPv6, and GitHub runners can't reach it.

### 2. Gmail secrets (for email-only newsletters)

The job skips the email step until these secrets exist. Everything else still runs.

1. At [console.cloud.google.com](https://console.cloud.google.com), create a project and enable the **Gmail API**.
2. Set up the **OAuth consent screen**:
   - User type: External.
   - Add the project Gmail address as a test user.
   - Then click **Publish app** to switch it to *In production*. While the app is in *Testing*, Google expires refresh tokens after 7 days and the email step would stop working. The app stays unverified, which is fine for your own account; you'll just click past a warning once.
3. Under **Credentials**, create an **OAuth client ID** of type *Desktop app* and download the JSON.
4. On your own computer, run:
   ```bash
   pip install google-auth-oauthlib
   python scripts/gmail_auth.py ~/Downloads/client_secret_XXXX.json
   ```
   When the browser opens, sign in as the **project** Gmail account.
5. Add the three values the script prints as repository secrets: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` and `GMAIL_REFRESH_TOKEN`.

The collector matches each email to a source in two ways: first by `sources.email_sender`, then by the sender's domain against the source's website domain. If a sender doesn't match, it's listed in that run's `collection_runs.notes`. Set `email_sender` for those sources and later runs will pick them up. Optionally, set a repository **variable** `GMAIL_QUERY` (e.g. `label:ds-index newer_than:3d`) to narrow which emails are read.

### 3. First run

In GitHub, go to **Actions → Daily collection → Run workflow**. Enter `P1` to start with the 24 priority sources, or leave it blank to run all of them. Then check the results:

```sql
select * from collection_runs order by run_id desc limit 5;
select source_id, feed_verified, consecutive_failures, feed_url from sources order by consecutive_failures desc;
select s.name, count(*) from items i join sources s using (source_id) group by 1 order by 2 desc;
```

## Local development

```bash
pip install -r requirements.txt
pytest tests/test_parsing.py                 # offline unit tests
TEST_DATABASE_URL=postgresql://... pytest    # end-to-end against a scratch Postgres (never production)
DATABASE_URL=... python -m collector.run --source NL004 --skip-email
```

## Not yet covered

- Podcast and YouTube transcripts. For now these items store the episode or video description; transcription is a later stage.
- Embeddings and topic tagging, which wait on the analytical plan.
- The weekly digest email.
