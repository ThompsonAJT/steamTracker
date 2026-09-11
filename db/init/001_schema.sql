-- =====================================================================
-- Steam tracker — initial schema
--
-- Design notes (these are the things worth defending in your write-up):
--
--  1. price_events is an EVENT LOG, not a daily snapshot. We only insert
--     a row when the price actually CHANGES. A daily snapshot of 100k
--     apps = 36.5M rows/year of mostly duplicate data. Event log for the
--     same period is maybe 1-2M rows. This is the correct model and it's
--     a real design decision you made.
--
--  2. player_counts IS a snapshot, because the value genuinely changes
--     every single poll. That's what makes it a time series, and that's
--     why it becomes a TimescaleDB hypertable.
--
--  3. Money is stored in INTEGER CENTS. Never use FLOAT for money.
--
--  4. Timestamps are TIMESTAMPTZ (timezone-aware), always stored in UTC.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;


-- ---------------------------------------------------------------------
-- apps — one row per Steam application. This is your master list.
-- ---------------------------------------------------------------------
CREATE TABLE apps (
    appid           INTEGER PRIMARY KEY,          -- Steam's own ID; no surrogate key needed
    name            TEXT        NOT NULL,
    app_type        TEXT,                         -- 'game', 'dlc', 'demo', 'music', ...
    is_free         BOOLEAN     NOT NULL DEFAULT FALSE,
    release_date    DATE,                         -- NULL for unreleased/TBA
    coming_soon     BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Ingestion bookkeeping. These drive your adaptive-polling research.
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_polled_at  TIMESTAMPTZ,                  -- when did we last hit the API for this app
    poll_priority   SMALLINT    NOT NULL DEFAULT 5,  -- 1 = poll often, 10 = rarely
    is_tracked      BOOLEAN     NOT NULL DEFAULT TRUE -- lets you switch apps off without deleting
);

-- Scheduler query: "give me the N apps most overdue for a poll."
CREATE INDEX idx_apps_poll_queue
    ON apps (poll_priority, last_polled_at NULLS FIRST)
    WHERE is_tracked;

-- Cheap case-insensitive search for the frontend later.
CREATE INDEX idx_apps_name_lower ON apps (LOWER(name));


-- ---------------------------------------------------------------------
-- price_events — append-only log of observed price CHANGES.
-- ---------------------------------------------------------------------
CREATE TABLE price_events (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appid               INTEGER     NOT NULL REFERENCES apps(appid) ON DELETE CASCADE,
    currency            CHAR(3)     NOT NULL DEFAULT 'USD',
    initial_cents       INTEGER     NOT NULL,     -- list price before discount
    final_cents         INTEGER     NOT NULL,     -- what you actually pay
    discount_percent    SMALLINT    NOT NULL DEFAULT 0,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_prices_nonneg CHECK (initial_cents >= 0 AND final_cents >= 0),
    CONSTRAINT chk_discount_range CHECK (discount_percent BETWEEN 0 AND 100)
);

-- Main query: "price history for app X, newest first."
CREATE INDEX idx_price_events_app_time
    ON price_events (appid, observed_at DESC);

-- Supports "what's on sale right now" without a full scan.
CREATE INDEX idx_price_events_discount
    ON price_events (observed_at DESC)
    WHERE discount_percent > 0;


-- ---------------------------------------------------------------------
-- player_counts — concurrent player samples. THIS is the hypertable.
-- ---------------------------------------------------------------------
CREATE TABLE player_counts (
    appid           INTEGER     NOT NULL REFERENCES apps(appid) ON DELETE CASCADE,
    player_count    INTEGER     NOT NULL,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_players_nonneg CHECK (player_count >= 0)
);

-- Turn it into a hypertable: Timescale transparently partitions by time
-- into 7-day "chunks". Queries and inserts look like normal SQL.
SELECT create_hypertable('player_counts', 'observed_at',
                         chunk_time_interval => INTERVAL '7 days');

CREATE INDEX idx_player_counts_app_time
    ON player_counts (appid, observed_at DESC);

-- Compress chunks older than 30 days. Typically 10-20x smaller.
-- Benchmarking this on/off is a ready-made results table for your paper.
ALTER TABLE player_counts SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'appid',
    timescaledb.compress_orderby   = 'observed_at DESC'
);
SELECT add_compression_policy('player_counts', INTERVAL '30 days');


-- ---------------------------------------------------------------------
-- tags — many-to-many between apps and Steam tags/genres.
-- ---------------------------------------------------------------------
CREATE TABLE tags (
    tag_id      SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE app_tags (
    appid       INTEGER NOT NULL REFERENCES apps(appid) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (appid, tag_id)
);

CREATE INDEX idx_app_tags_tag ON app_tags (tag_id);


-- ---------------------------------------------------------------------
-- poll_log — every API call you make. Do NOT skip this table.
--
-- This is your research instrument. Without it you cannot report request
-- volume, error/rate-limit rates, or change-detection latency, and those
-- numbers ARE the evaluation section of your paper.
-- ---------------------------------------------------------------------
CREATE TABLE poll_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appid           INTEGER,                      -- nullable: some calls aren't app-specific
    endpoint        TEXT        NOT NULL,         -- 'appdetails', 'GetNumberOfCurrentPlayers'
    scheduler_name  TEXT,                         -- 'round_robin' | 'popularity' | 'adaptive'
    http_status     SMALLINT,
    latency_ms      INTEGER,
    produced_change BOOLEAN     NOT NULL DEFAULT FALSE, -- did this call reveal new data?
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_poll_log_time ON poll_log (requested_at DESC);
CREATE INDEX idx_poll_log_scheduler ON poll_log (scheduler_name, requested_at DESC);
