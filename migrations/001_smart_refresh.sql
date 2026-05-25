-- Smart auto-refresh migration (2026-05-25)
-- Run once against the production Postgres (Supabase) before/at deploy.
-- Idempotent: safe to re-run.

-- 1) Lock flag: marks human-owned clusters (CSV upload / manual edit) so
--    smart-refresh never auto-regenerates over them.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;

-- 2) Per-scope generation record. One row per (block_name, commodity), holding
--    the fingerprint (algorithm version + params + village data) used at last
--    generation. A scope is rebuilt on read only when this fingerprint is stale
--    and the scope isn't locked. Exists even for zero-cluster scopes so empty
--    results aren't rebuilt on every load.
CREATE TABLE IF NOT EXISTS cluster_generation (
    block_name   TEXT NOT NULL,
    commodity    TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (block_name, commodity)
);

-- After this migration + deploy: cluster_generation is empty, so every scope's
-- stored fingerprint is missing => the first view of each (block, commodity)
-- regenerates it once with the current algorithm (ALGO_VERSION=3) and stores the
-- fingerprint. This auto-heals the stale cap-50 Dairy clusters (CHEWNI fix)
-- because they are Proposed, not finalized/locked.
