# leaf_flask tests

Pytest suite covering the changes from the 9 May 2026 Faiz call. Focused on
pure functions and route guards so a Postgres instance is not required.

## Run

```bash
cd leaf_flask
pytest tests/ -v
```

## What's covered

| File | What it verifies |
|---|---|
| `test_smoke.py` | App imports, modules import, defaults sane, cluster routes registered |
| `test_clustering.py` | #18 single-village exception, #19 orphan merge, soft cap, `_emit_cluster` invariants |
| `test_csv_round_trip.py` | #10 download schema (`cluster_num` present, no lat/long), #12 upload backfills lat/long from village master, legacy lat/long still accepted, unknown village raises |
| `test_admin_guard.py` | #9 regenerate returns 403 without admin flag, accepts query or header form, `_is_admin_request` helper truth table |

## What's not covered

- End-to-end against a real DB. The `get_clusters`, `regenerate_clusters`,
  and `replace_clusters_from_records` functions hit Postgres - exercise
  them manually via the dev server (`flask run`) or `curl` against a
  staging env.
- Browser UI (cluster ring rendering, search-box flash, side-panel
  sections). Open the cluster planner page and click around.
