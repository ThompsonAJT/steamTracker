"""
ingest.py — pull Steam data into Postgres.

The only genuinely interesting logic here is change detection: we compare
against the most recent price_event and only INSERT when something moved.
That is what turns a scraper into a price-history tracker.

    python ingest.py            # one pass over SEED_APPS
    python ingest.py --loop     # run forever on a schedule
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

ENGINE = create_engine(os.environ["DATABASE_URL"], future=True)

STORE_URL = "https://store.steampowered.com/api/appdetails"
PLAYERS_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"

# Steam tolerates roughly 200 requests / 5 min from one IP. We make two
# calls per app, so ~1.6s between apps keeps us comfortably under.
SECONDS_BETWEEN_APPS = 2.0

# A starter set of well-known appids. Enough to make charts look real.
SEED_APPS = [
    730, 570, 440, 578080, 1172470, 271590, 1091500, 292030, 1245620,
    252490, 431960, 1085660, 359550, 381210, 1938090, 236390, 304930,
    413150, 105600, 322330, 892970, 550, 620, 400, 220, 4000, 10,
    242760, 648800, 251570, 346110, 232090, 739630, 1966720, 108600,
    427520, 294100, 255710, 813780, 289070,
]


# ---------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------
def fetch_details(client: httpx.Client, appid: int) -> tuple[dict | None, int, int]:
    start = time.perf_counter()
    try:
        r = client.get(STORE_URL, params={"appids": appid, "cc": "us", "l": "en"})
        latency = int((time.perf_counter() - start) * 1000)
        if r.status_code != 200:
            return None, r.status_code, latency
        entry = r.json().get(str(appid), {})
        if not entry.get("success"):
            return None, 200, latency
        return entry["data"], 200, latency
    except httpx.HTTPError:
        return None, 0, int((time.perf_counter() - start) * 1000)


def fetch_players(client: httpx.Client, appid: int) -> tuple[int | None, int, int]:
    start = time.perf_counter()
    try:
        r = client.get(PLAYERS_URL, params={"appid": appid})
        latency = int((time.perf_counter() - start) * 1000)
        if r.status_code != 200:
            return None, r.status_code, latency
        body = r.json().get("response", {})
        if body.get("result") != 1:
            return None, 200, latency
        return body.get("player_count"), 200, latency
    except httpx.HTTPError:
        return None, 0, int((time.perf_counter() - start) * 1000)


# ---------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------
def upsert_app(conn, appid: int, data: dict) -> None:
    release = data.get("release_date", {}) or {}
    conn.execute(
        text("""
            INSERT INTO apps (appid, name, app_type, is_free, coming_soon, last_polled_at)
            VALUES (:appid, :name, :type, :is_free, :coming_soon, NOW())
            ON CONFLICT (appid) DO UPDATE SET
                name           = EXCLUDED.name,
                app_type       = EXCLUDED.app_type,
                is_free        = EXCLUDED.is_free,
                coming_soon    = EXCLUDED.coming_soon,
                last_polled_at = NOW()
        """),
        {
            "appid": appid,
            "name": data.get("name", f"Unknown {appid}"),
            "type": data.get("type"),
            "is_free": bool(data.get("is_free")),
            "coming_soon": bool(release.get("coming_soon")),
        },
    )


def record_price(conn, appid: int, price: dict | None) -> bool:
    """Insert a price_event ONLY if it differs from the latest one.

    Returns True if a new row was written (i.e. the price changed).
    """
    if not price:  # free game, unreleased, or region-locked
        return False

    new = (
        price.get("initial", 0),
        price.get("final", 0),
        price.get("discount_percent", 0),
    )

    latest = conn.execute(
        text("""
            SELECT initial_cents, final_cents, discount_percent
            FROM price_events
            WHERE appid = :appid
            ORDER BY observed_at DESC
            LIMIT 1
        """),
        {"appid": appid},
    ).fetchone()

    if latest is not None and tuple(latest) == new:
        return False  # unchanged — this is the common case, and the point

    conn.execute(
        text("""
            INSERT INTO price_events
                (appid, currency, initial_cents, final_cents, discount_percent)
            VALUES (:appid, :currency, :initial, :final, :discount)
        """),
        {
            "appid": appid,
            "currency": price.get("currency", "USD")[:3],
            "initial": new[0],
            "final": new[1],
            "discount": new[2],
        },
    )
    return True


def record_players(conn, appid: int, count: int | None) -> None:
    if count is None:
        return
    conn.execute(
        text("INSERT INTO player_counts (appid, player_count) VALUES (:appid, :count)"),
        {"appid": appid, "count": count},
    )


def log_call(conn, appid, endpoint, status, latency, changed) -> None:
    conn.execute(
        text("""
            INSERT INTO poll_log
                (appid, endpoint, scheduler_name, http_status, latency_ms, produced_change)
            VALUES (:appid, :endpoint, 'seed', :status, :latency, :changed)
        """),
        {
            "appid": appid, "endpoint": endpoint, "status": status,
            "latency": latency, "changed": changed,
        },
    )


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------
def run_pass() -> None:
    started = datetime.now(timezone.utc)
    apps_seen = price_changes = player_rows = failures = 0

    with httpx.Client(timeout=20.0, headers={"User-Agent": "steamtracker/0.1"}) as client:
        for i, appid in enumerate(SEED_APPS, start=1):
            data, status, latency = fetch_details(client, appid)

            with ENGINE.begin() as conn:
                if data is None:
                    failures += 1
                    log_call(conn, appid, "appdetails", status, latency, False)
                else:
                    upsert_app(conn, appid, data)
                    changed = record_price(conn, appid, data.get("price_overview"))
                    log_call(conn, appid, "appdetails", status, latency, changed)
                    apps_seen += 1
                    price_changes += int(changed)

            count, pstatus, platency = fetch_players(client, appid)
            with ENGINE.begin() as conn:
                record_players(conn, appid, count)
                log_call(conn, appid, "players", pstatus, platency, count is not None)
            player_rows += int(count is not None)

            name = (data or {}).get("name", "?")
            print(f"[{i:>3}/{len(SEED_APPS)}] {appid:<8} {name[:40]:<40} "
                  f"{'PRICE CHANGE' if data and price_changes else ''}")

            time.sleep(SECONDS_BETWEEN_APPS)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"\napps updated:   {apps_seen}")
    print(f"price changes:  {price_changes}")
    print(f"player samples: {player_rows}")
    print(f"failures:       {failures}")
    print(f"elapsed:        {elapsed:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true",
                        help="run continuously instead of a single pass")
    args = parser.parse_args()

    if not args.loop:
        run_pass()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler

    run_pass()  # immediate first pass so you aren't waiting
    sched = BlockingScheduler()
    sched.add_job(run_pass, "interval", minutes=30, max_instances=1)
    print("\nScheduler running — Ctrl-C to stop.")
    sched.start()


if __name__ == "__main__":
    main()
