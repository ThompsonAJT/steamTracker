# Steam Tracker — setup

## Folder layout

```
steamtracker/
├── docker-compose.yml
├── .env                  ← you create this (see below), never commit it
├── db/
│   └── init/
│       └── 001_schema.sql
└── fetch_one.py
```

## 1. Create `.env`

```
POSTGRES_USER=steam
POSTGRES_PASSWORD=pick_something_real
POSTGRES_DB=steamtracker
```

Add `.env` to `.gitignore` immediately.

## 2. Start the database

```bash
docker compose up -d
docker compose logs -f db      # Ctrl-C once you see "database system is ready"
```

Connect with TablePlus or DBeaver:

- host `localhost`, port **5433**, database `steamtracker`, user/password from `.env`

Verify the schema loaded:

```sql
SELECT tablename FROM pg_tables WHERE schemaname = 'public';
```

You should see: apps, price_events, player_counts, tags, app_tags, poll_log.

## 3. Fetch one app

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install httpx
python fetch_one.py 730
```

## Gotchas that will bite you

- **The init script only runs on an empty volume.** If you edit `001_schema.sql`
  after the first startup, nothing happens. To reset during early development:
  `docker compose down -v` (the `-v` wipes the volume), then `up -d` again.
  Once you have real data, stop doing this and switch to Alembic migrations.
- **`price_overview` is missing for free games.** Always use `.get()`.
- **The store API is undocumented and unversioned.** It rate-limits at roughly
  200 requests per 5 minutes per IP. Do not hammer it while testing — put a
  sleep between calls from the very first loop you write.
- **`appdetails` only accepts one appid at a time** in practice, despite the
  plural parameter name. Plan your request budget around that.

## Next steps, in order

1. Read `sample_730.json` end to end. Decide which fields you actually want.
2. Show the schema to your advisor before writing ingestion code.
3. Write `ingest.py`: loop over 10 hardcoded appids, insert into `apps` +
   `price_events`, and log every call into `poll_log`.
4. Add a "only insert a price_event if it differs from the latest one" check.
   That's your change-detection logic — the core of the whole project.
5. Wrap it in APScheduler.
