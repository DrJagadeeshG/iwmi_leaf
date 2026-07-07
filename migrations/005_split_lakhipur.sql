-- 005_split_lakhipur.sql
-- Split the two genuinely-distinct LAKHIPUR blocks that share a name:
--   LAKHIPUR (Cachar, Barak valley)  and  LAKHIPUR (Goalpara, western Assam).
-- The village master (villages.csv) and block_values.csv are renamed to
-- "LAKHIPUR (CACHAR)" / "LAKHIPUR (GOALPARA)" in the same change. Here we
-- relabel the already-stored clusters IN PLACE, keyed on each cluster's own
-- (correct) district_name, so ALL locked cadre data (pashu_sakhi,
-- block_coordinator, locked/finalized flags, cluster_villages) is preserved --
-- this is a pure rename, never a regeneration.

BEGIN;

UPDATE clusters SET block_name = 'LAKHIPUR (CACHAR)'
 WHERE block_name = 'LAKHIPUR' AND upper(district_name) = 'CACHAR';

UPDATE clusters SET block_name = 'LAKHIPUR (GOALPARA)'
 WHERE block_name = 'LAKHIPUR' AND upper(district_name) = 'GOALPARA';

-- The old ('LAKHIPUR', commodity) fingerprint rows are now orphaned (that block
-- name no longer exists in the master). The new-name scopes are locked (cadre)
-- so they will not auto-regenerate; drop the stale fingerprints to keep the
-- refresh/coverage bookkeeping clean.
DELETE FROM cluster_generation WHERE block_name = 'LAKHIPUR';

-- Migration-window guard: the daily coverage refresh is near-due. Push its
-- last_run forward so it cannot fire in the gap between this DB relabel and the
-- villages.csv/block_values.csv deploy and regenerate a no-cadre 'LAKHIPUR'
-- from the pre-deploy master. Harmless to skip one idempotent daily run.
UPDATE maintenance_run SET last_run = now() WHERE job = 'refresh_all_coverage';

COMMIT;
