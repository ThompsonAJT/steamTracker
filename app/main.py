"""
app/main.py — minimal API + dashboard.

    uvicorn app.main:app --reload
    http://localhost:8000
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, text

load_dotenv()

ENGINE = create_engine(os.environ["DATABASE_URL"], future=True)
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Steam Tracker")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/apps")
def list_apps(q: str = "", tag: str = "", limit: int = 50):
    """Search apps, with their most recent price attached."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT a.appid, a.name, a.app_type, a.is_free,
                       p.final_cents, p.initial_cents, p.discount_percent
                FROM apps a
                LEFT JOIN LATERAL (
                    SELECT final_cents, initial_cents, discount_percent
                    FROM price_events
                    WHERE appid = a.appid
                    ORDER BY observed_at DESC
                    LIMIT 1
                ) p ON TRUE
                WHERE (:q = '' OR LOWER(a.name) LIKE '%' || LOWER(:q) || '%')
                  AND (:tag = '' OR EXISTS (
                      SELECT 1 FROM app_tags at
                      JOIN tags t ON t.tag_id = at.tag_id
                      WHERE at.appid = a.appid AND t.name = :tag
                  ))
                ORDER BY a.name
                LIMIT :limit
            """),
            {"q": q, "tag": tag, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/tags")
def list_tags():
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT t.name, COUNT(*) AS app_count
                FROM tags t
                JOIN app_tags at ON at.tag_id = t.tag_id
                GROUP BY t.name
                ORDER BY t.name
            """)
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/apps/{appid}/prices")
def price_history(appid: int):
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT observed_at, initial_cents, final_cents, discount_percent
                FROM price_events
                WHERE appid = :appid
                ORDER BY observed_at
            """),
            {"appid": appid},
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/apps/{appid}/players")
def player_history(appid: int, hours: int = 168):
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT observed_at, player_count
                FROM player_counts
                WHERE appid = :appid
                  AND observed_at > NOW() - (:hours || ' hours')::INTERVAL
                ORDER BY observed_at
            """),
            {"appid": appid, "hours": hours},
        ).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/deals")
def current_deals(limit: int = 25):
    """Apps whose latest price event carries a discount."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT DISTINCT ON (a.appid)
                       a.appid, a.name, p.final_cents, p.initial_cents,
                       p.discount_percent, p.observed_at
                FROM apps a
                JOIN price_events p ON p.appid = a.appid
                ORDER BY a.appid, p.observed_at DESC
            """)
        ).mappings().all()
    deals = [dict(r) for r in rows if r["discount_percent"] > 0]
    deals.sort(key=lambda d: d["discount_percent"], reverse=True)
    return deals[:limit]


@app.get("/api/stats")
def stats():
    with ENGINE.connect() as conn:
        def scalar(sql: str):
            return conn.execute(text(sql)).scalar() or 0
        return {
            "apps": scalar("SELECT COUNT(*) FROM apps"),
            "price_events": scalar("SELECT COUNT(*) FROM price_events"),
            "player_samples": scalar("SELECT COUNT(*) FROM player_counts"),
            "api_calls": scalar("SELECT COUNT(*) FROM poll_log"),
            "error_rate": round(
                scalar("SELECT COUNT(*) FROM poll_log WHERE http_status <> 200")
                / max(scalar("SELECT COUNT(*) FROM poll_log"), 1) * 100, 2),
        }
