"""Nightly logical backup of the cluster tables to Supabase Storage.

Why Storage (not a file on disk): the app runs on Render's ephemeral filesystem,
so local files vanish on restart/redeploy. Storage is durable and lives in the
same Supabase project. Everything here is IPv4 HTTPS (Supabase REST + Storage
API) using SUPABASE_SECRET_KEY - deliberately independent of the direct Postgres
connection (which is IPv6-only), so a backup can run even when IPv6 is flaky.

Snapshots go to bucket `db-backups` as `<YYYY-MM-DD>/<table>.csv.gz`; snapshots
older than RETAIN_DAYS are pruned. Driven nightly by scheduler.py.
"""
import csv
import gzip
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
KEY = os.environ.get("SUPABASE_SECRET_KEY") or ""
BUCKET = "db-backups"
TABLES = ["clusters", "cluster_villages", "cluster_generation"]
RETAIN_DAYS = 14


def _headers(extra=None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if extra:
        h.update(extra)
    return h


def _open(url, method="GET", headers=None, data=None, timeout=120):
    r = urllib.request.Request(url, method=method, data=data)
    for k, v in _headers(headers).items():
        r.add_header(k, v)
    return urllib.request.urlopen(r, timeout=timeout)


def _fetch_all(table):
    """Page through a table via PostgREST (1000 rows/request)."""
    out, step = [], 1000
    for start in range(0, 5_000_000, step):
        resp = _open(f"{BASE}/rest/v1/{table}?select=*",
                     headers={"Range": f"{start}-{start + step - 1}"})
        rows = json.loads(resp.read())
        out.extend(rows)
        if len(rows) < step:
            break
    return out


def _csv_gz(rows):
    if not rows:
        return gzip.compress(b"")
    # Union of keys across rows keeps every column even if some are null-omitted.
    cols = list({k for r in rows for k in r.keys()})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return gzip.compress(buf.getvalue().encode("utf-8"))


def _ensure_bucket():
    try:
        _open(f"{BASE}/storage/v1/bucket", method="POST",
              headers={"Content-Type": "application/json"},
              data=json.dumps({"id": BUCKET, "name": BUCKET, "public": False}).encode(),
              timeout=30)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 409):  # already-exists is fine
            raise


def _upload(object_path, blob):
    _open(f"{BASE}/storage/v1/object/{BUCKET}/{object_path}", method="POST",
          headers={"Content-Type": "application/gzip", "x-upsert": "true"}, data=blob)


def _prune(cutoff_date_str):
    """Delete snapshot folders whose date prefix is older than the cutoff."""
    try:
        resp = _open(f"{BASE}/storage/v1/object/list/{BUCKET}", method="POST",
                     headers={"Content-Type": "application/json"},
                     data=json.dumps({"prefix": "", "limit": 1000}).encode(), timeout=60)
        items = json.loads(resp.read())
        stale = sorted({it["name"] for it in items if it.get("name", "") < cutoff_date_str})
        for folder in stale:
            for t in TABLES:
                try:
                    _open(f"{BASE}/storage/v1/object/{BUCKET}/{folder}/{t}.csv.gz",
                          method="DELETE", timeout=30)
                except Exception:
                    pass
        return stale
    except Exception:
        return []


def backup_to_storage(now=None):
    """Snapshot the cluster tables to Supabase Storage. Returns a summary dict.
    No-op (returns skipped) when Supabase creds are absent (e.g. local/tests)."""
    if not (BASE and KEY):
        return {"skipped": "no SUPABASE_URL / SUPABASE_SECRET_KEY"}
    now = now or datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    _ensure_bucket()
    summary = {"date": date_str, "tables": {}}
    for t in TABLES:
        rows = _fetch_all(t)
        _upload(f"{date_str}/{t}.csv.gz", _csv_gz(rows))
        summary["tables"][t] = len(rows)
    cutoff = (now - timedelta(days=RETAIN_DAYS)).strftime("%Y-%m-%d")
    summary["pruned"] = _prune(cutoff)
    return summary
