-- District coordinator migration (2026-06-07)
-- Run once against production Postgres (Supabase) before/at deploy. Idempotent.
--
-- Adds the `district_coordinator` column so the Contact Persons card's DC
-- (District Coordinator) row has a real data source, alongside the existing
-- block_coordinator (BC) and pashu_sakhi (PS). Filled via the cluster CSV
-- edit/import cycle; defaults to empty for existing rows.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS district_coordinator TEXT;
