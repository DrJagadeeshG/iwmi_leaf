-- Cluster name migration (2026-06-08)
-- Run once against production Postgres (Supabase) before/at deploy. Idempotent.
--
-- Adds the `cluster_name` column: an editable display-name OVERRIDE for the
-- auto-generated `cluster_code` (e.g. MO-BH-GO-01). When set via the cluster CSV
-- edit/import cycle, the frontend shows cluster_name instead of the auto code;
-- NULL/empty keeps the auto code. Defaults to empty for existing rows.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS cluster_name TEXT;
