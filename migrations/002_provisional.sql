-- Provisional clusters migration (2026-05-25)
-- Run once against production Postgres (Supabase) before/at deploy. Idempotent.
--
-- Adds the `provisional` flag so below-floor village groups (surfaced by Pass D
-- when emit_provisional is on) can be stored and shown with a UI badge, kept
-- separate from fundable clusters.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS provisional BOOLEAN NOT NULL DEFAULT FALSE;
