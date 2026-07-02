-- LEAF DSS clustering schema
-- Tables: clusters, cluster_villages, infrastructure, cluster_generation, maintenance_run

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id        TEXT PRIMARY KEY,
    commodity         TEXT NOT NULL,
    block_name        TEXT NOT NULL,
    district_name     TEXT,
    total_members     INTEGER,
    max_span_km       NUMERIC(8, 3),
    centroid_lat      NUMERIC(10, 6),
    centroid_lon      NUMERIC(10, 6),
    pashu_sakhi       TEXT,
    block_coordinator TEXT,
    -- District Coordinator for the Contact Persons card (DC row). Set via the
    -- cluster CSV edit/import cycle; NULL/empty until assigned.
    district_coordinator TEXT,
    -- Editable display-name override for the auto-generated cluster_code. Set via
    -- the cluster CSV edit/import cycle; NULL/empty keeps the auto code.
    cluster_name      TEXT,
    finalized         BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE when a human owns this cluster (CSV upload or manual edit). Locked
    -- scopes are never auto-regenerated, so smart-refresh can't wipe edits.
    locked            BOOLEAN NOT NULL DEFAULT FALSE,
    -- TRUE for below-floor groups surfaced for review (not fundable). Shown in
    -- the UI with a "provisional" badge and excluded from fundable counts.
    provisional       BOOLEAN NOT NULL DEFAULT FALSE,
    dashboard         JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clusters_block     ON clusters(block_name);
CREATE INDEX IF NOT EXISTS idx_clusters_commodity ON clusters(commodity);
CREATE INDEX IF NOT EXISTS idx_clusters_district  ON clusters(district_name);

-- Per-scope generation record for smart auto-refresh. One row per
-- (block_name, commodity). `fingerprint` captures the algorithm version,
-- params and village data used; a scope is regenerated on read only when the
-- current fingerprint differs (stale) AND the scope isn't locked/finalized.
-- Exists even for scopes that yield zero clusters, so empty results aren't
-- rebuilt on every load.
CREATE TABLE IF NOT EXISTS cluster_generation (
    block_name   TEXT NOT NULL,
    commodity    TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (block_name, commodity)
);

CREATE TABLE IF NOT EXISTS cluster_villages (
    id            BIGSERIAL PRIMARY KEY,
    cluster_id    TEXT NOT NULL REFERENCES clusters(cluster_id) ON DELETE CASCADE,
    vill_name     TEXT,
    gp_name       TEXT,
    lat           NUMERIC(10, 6),
    "long"        NUMERIC(10, 6),
    members       INTEGER,
    village_index INTEGER,
    position      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cv_cluster ON cluster_villages(cluster_id);

CREATE TABLE IF NOT EXISTS infrastructure (
    id            BIGSERIAL PRIMARY KEY,
    type          TEXT NOT NULL,
    name          TEXT NOT NULL,
    lat           NUMERIC(10, 6) NOT NULL,
    "long"        NUMERIC(10, 6) NOT NULL,
    district_name TEXT,
    block_name    TEXT,
    gp_name       TEXT,
    vill_name     TEXT
);
CREATE INDEX IF NOT EXISTS idx_infra_type  ON infrastructure(type);
CREATE INDEX IF NOT EXISTS idx_infra_block ON infrastructure(block_name);

-- Bookkeeping for background maintenance jobs. Currently one row:
-- 'refresh_all_coverage', stamped by the daily scheduler (scheduler.py) each
-- time it rebuilds whole-state cluster coverage. `last_run` gates the once-a-day
-- interval; `last_summary` keeps the last run's counts for debugging. Created at
-- runtime too (CREATE TABLE IF NOT EXISTS in scheduler._run_if_due).
CREATE TABLE IF NOT EXISTS maintenance_run (
    job          TEXT PRIMARY KEY,
    last_run     TIMESTAMPTZ,
    last_summary JSONB
);
