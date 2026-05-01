-- LEAF DSS clustering schema
-- Tables: clusters, cluster_villages, infrastructure

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
    finalized         BOOLEAN NOT NULL DEFAULT FALSE,
    dashboard         JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clusters_block     ON clusters(block_name);
CREATE INDEX IF NOT EXISTS idx_clusters_commodity ON clusters(commodity);
CREATE INDEX IF NOT EXISTS idx_clusters_district  ON clusters(district_name);

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
