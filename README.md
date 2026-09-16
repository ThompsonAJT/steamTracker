# Steam Tracker

A SteamDB-style tracker for price history, concurrent player counts, and
current deals across a set of popular Steam games.

**Live:** https://steamtracker-production.up.railway.app

## Stack

Python 3 · httpx · PostgreSQL + TimescaleDB · SQLAlchemy Core · APScheduler ·
FastAPI · vanilla JS + Chart.js. No React, no frontend build step.

Deployed on Railway as three services: `steamTracker` (the FastAPI dashboard),
`worker` (the continuous ingest loop), and `steamtracker-db` (TimescaleDB),
talking to each other over Railway's private network.

## Folder layout

```
steamtracker/
├── bootstrap.sh               # local dev setup, run once
├── docker-compose.yml         # local TimescaleDB on host port 5433
├── requirements.txt
├── Procfile                   # start commands Railway reads (web / worker)
├── ingest.py                  # fetch loop + change detection
├── db/init/001_schema.sql     # schema, runs once on first container start
└── app/
    ├── main.py                # FastAPI
    └── static/index.html      # dashboard
```

## Local development

```bash
chmod +x bootstrap.sh
./bootstrap.sh                 # creates .env, venv, starts local Postgres
source .venv/bin/activate
python ingest.py               # one pass over the seed list
uvicorn app.main:app --reload
open http://localhost:8000
```

## Design decisions worth knowing about

- **`price_events` is an event log, not daily snapshots.** A row is only
  inserted when the price actually changes. Snapshotting 100k apps daily
  would be ~36M rows/year of mostly duplicates; the event log for the same
  period is closer to 1-2M rows.
- **`player_counts` is a genuine time series** — every poll is a new value —
  so it's a TimescaleDB hypertable with a 30-day compression policy.
- **Money is stored in integer cents**, never floats.
- **`poll_log` records every API call** (latency, status, whether it produced
  a change), which is what makes rate-limit and failure-rate numbers
  possible to report honestly rather than guessed at.

## Gotchas

- Steam's store API tolerates roughly 200 requests / 5 min per IP.
  `ingest.py` sleeps 2s between apps — don't remove that.
- `appdetails` takes one appid per call despite the plural parameter name.
- `price_overview` is absent for free and unreleased games — always `.get()`.
- `db/init/`'s schema only runs on an empty Postgres volume. Editing the SQL
  after first startup does nothing locally; on Railway it needs to be applied
  manually against the running database.
- A scheduler running on a laptop needs `misfire_grace_time=None` — the
  default silently drops any run whose fire time passed while the machine
  was asleep, instead of running it late.

## Deploying (Railway)

Each service deploys independently via the Railway CLI:

```bash
railway up -s steamTracker
railway up -s worker
```

GitHub auto-deploy is configured, so a push to `main` should also trigger
both services to redeploy on its own.
