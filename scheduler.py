"""Daily maintenance scheduler for LEAF DSS.

Runs ``villages.refresh_all_coverage()`` once a day so the whole-state cluster
export/report always covers every block - not just the ones someone happened to
open on the map (the lazy get_or_regenerate path, which otherwise made the
report show ~40% of the true members; Faiz 2026-07-02).

Also runs a daily logical backup of the cluster tables to Supabase Storage
(``db_backup.backup_to_storage``) so there is always an off-dyno restore point.

Self-contained by design (no extra Render service / env to manage): a daemon
thread wakes hourly, and a Postgres advisory lock + a last-run stamp in the
``maintenance_run`` table ensure each job runs at most once per interval even
when several gunicorn workers each start a thread. The coverage sweep is also
exposed manually via ``POST /api/clusters/refresh-all`` (the "Refresh all
clusters" button on /update); the backup is daily-only.
"""

import threading
import time
import traceback

from psycopg2.extras import Json

from db import get_conn, is_configured

JOB = "refresh_all_coverage"
BACKUP_JOB = "db_backup"
# Stable, app-unique 64-bit keys for pg_advisory_lock so only one process runs
# each job at a time. Distinct keys let the coverage sweep and the backup run
# independently. Changing a value would let two runs overlap.
_LOCK_KEY = 728104531
_BACKUP_LOCK_KEY = 728104532
_CHECK_EVERY_S = 3600   # wake once an hour...
_MIN_INTERVAL_H = 24    # ...but only actually run when a day has passed
_STARTUP_DELAY_S = 120  # let app boot / preload settle before any heavy regen

_started = False
_start_lock = threading.Lock()


def _locked_run(force: bool) -> None:
    """Acquire the advisory lock and run the full-coverage refresh, then stamp
    the run. When ``force`` is False the run is skipped if it happened within the
    interval (the daily path); when True the interval check is bypassed (the
    manual "Refresh" button). No-op for any caller that fails to get the lock, so
    concurrent clicks / the daily tick never overlap."""
    from villages import refresh_all_coverage  # deferred: avoids import cycle

    with get_conn() as conn:
        prev_autocommit = conn.autocommit
        conn.autocommit = True  # DDL + advisory lock want their own txn boundaries
        try:
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS maintenance_run ("
                "job text PRIMARY KEY, last_run timestamptz, last_summary jsonb)"
            )
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
            if not cur.fetchone()[0]:
                return  # another worker/process is already running it
            try:
                if not force:
                    cur.execute("SELECT last_run FROM maintenance_run WHERE job = %s", (JOB,))
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        cur.execute(
                            "SELECT (now() - %s) >= make_interval(hours => %s)",
                            (row[0], _MIN_INTERVAL_H),
                        )
                        if not cur.fetchone()[0]:
                            return  # ran within the interval - skip
                summary = refresh_all_coverage()
                cur.execute(
                    "INSERT INTO maintenance_run (job, last_run, last_summary) "
                    "VALUES (%s, now(), %s) "
                    "ON CONFLICT (job) DO UPDATE "
                    "SET last_run = now(), last_summary = EXCLUDED.last_summary",
                    (JOB, Json({k: summary.get(k) for k in
                                ("blocks", "regenerated", "fresh", "skipped_locked")})),
                )
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
        finally:
            conn.autocommit = prev_autocommit  # don't pollute the pooled connection


def _backup_if_due() -> None:
    """Once a day, snapshot the cluster tables to Supabase Storage. Advisory-lock
    gated (own key) + interval-gated via maintenance_run so it runs at most once
    per day across all workers. Independent of the manual Refresh button."""
    from db_backup import backup_to_storage  # deferred: keeps import light

    with get_conn() as conn:
        prev_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS maintenance_run ("
                "job text PRIMARY KEY, last_run timestamptz, last_summary jsonb)"
            )
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_BACKUP_LOCK_KEY,))
            if not cur.fetchone()[0]:
                return
            try:
                cur.execute("SELECT last_run FROM maintenance_run WHERE job = %s", (BACKUP_JOB,))
                row = cur.fetchone()
                if row and row[0] is not None:
                    cur.execute("SELECT (now() - %s) >= make_interval(hours => %s)",
                                (row[0], _MIN_INTERVAL_H))
                    if not cur.fetchone()[0]:
                        return  # backed up within the interval - skip
                summary = backup_to_storage()
                cur.execute(
                    "INSERT INTO maintenance_run (job, last_run, last_summary) "
                    "VALUES (%s, now(), %s) "
                    "ON CONFLICT (job) DO UPDATE "
                    "SET last_run = now(), last_summary = EXCLUDED.last_summary",
                    (BACKUP_JOB, Json(summary)),
                )
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_BACKUP_LOCK_KEY,))
        finally:
            conn.autocommit = prev_autocommit


def trigger_async(force: bool = True) -> None:
    """Kick off a coverage refresh in a background daemon thread and return
    immediately. Used by the manual Refresh endpoint so a full rebuild (which can
    take a while when many blocks are stale) never blocks / times out the HTTP
    request. The advisory lock in _locked_run makes overlapping triggers safe."""
    threading.Thread(
        target=lambda: _guarded(force), name="leaf-refresh-trigger", daemon=True
    ).start()


def _guarded(force: bool) -> None:
    try:
        _locked_run(force)
    except Exception:  # a background run must never crash the process
        traceback.print_exc()


def _loop() -> None:
    time.sleep(_STARTUP_DELAY_S)
    while True:
        _guarded(force=False)
        try:
            _backup_if_due()
        except Exception:  # a backup failure must not stop the scheduler
            traceback.print_exc()
        time.sleep(_CHECK_EVERY_S)


def start_scheduler() -> None:
    """Start the daily maintenance thread once per process. No-op without a
    configured database (e.g. tests / local runs with no DATABASE_URL)."""
    global _started
    if not is_configured():
        return
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_loop, name="leaf-daily-maintenance", daemon=True).start()
