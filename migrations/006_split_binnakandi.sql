-- 006_split_binnakandi.sql
-- Split the two genuinely-distinct BINNAKANDI blocks that share a name:
--   BINNAKANDI (Hojai, 112 villages)  and  BINNAKANDI (Cachar, 62 villages),
-- ~151 km apart, both real (both in block_values.csv; Hojai was carved from the
-- legacy Nowgaon district). The name collision made Hojai's Binnakandi surface
-- under Cachar (Faiz / user, Hojai issue #2). Same pattern as 005_split_lakhipur.
--
-- villages.csv and block_values.csv are renamed to "BINNAKANDI (HOJAI)" /
-- "BINNAKANDI (CACHAR)" in the same change. Here we relabel the already-stored
-- clusters in place, keyed on each cluster's own district_name. Binnakandi has
-- NO locked/cadre clusters, so this is a plain rename with nothing to protect,
-- but we relabel (not regenerate) to keep it clean and consistent with 005.

BEGIN;

UPDATE clusters SET block_name = 'BINNAKANDI (HOJAI)'
 WHERE block_name = 'BINNAKANDI' AND upper(district_name) = 'HOJAI';

UPDATE clusters SET block_name = 'BINNAKANDI (CACHAR)'
 WHERE block_name = 'BINNAKANDI' AND upper(district_name) = 'CACHAR';

-- Drop the now-orphaned ('BINNAKANDI', commodity) fingerprint rows so the
-- refresh/coverage bookkeeping stays clean; the new-name scopes recompute their
-- fingerprint on next access.
DELETE FROM cluster_generation WHERE block_name = 'BINNAKANDI';

-- Migration-window guard: keep the near-due daily coverage refresh from firing
-- in the gap between this relabel and the villages.csv deploy (it would
-- otherwise regenerate a 'BINNAKANDI' from the pre-deploy master). Harmless to
-- skip one idempotent daily run.
UPDATE maintenance_run SET last_run = now() WHERE job = 'refresh_all_coverage';

COMMIT;
