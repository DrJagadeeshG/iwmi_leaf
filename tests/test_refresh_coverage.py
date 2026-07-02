"""Regression tests for the whole-state coverage refresh (villages.refresh_all_coverage).

Faiz's concern (2026-07-02): the daily "run the complete thing" refresh must NOT
wipe changes made by the cadre. These tests pin that guarantee down without a
Postgres instance by stubbing the DB cursor and the per-scope regen.
"""
import contextlib

import pandas as pd

import villages


def _install_fakes(monkeypatch, gen_rows, locked_rows, fresh_key):
    """Wire villages.* so refresh_all_coverage runs against two synthetic blocks
    x two commodities with the given generation/locked snapshot. Returns the list
    that records every (block, commodity) actually handed to regenerate_clusters."""
    monkeypatch.setattr(villages, "COMMODITIES", ["Dairy", "Goatery"])
    df = pd.DataFrame([
        {"district_name": "D", "block_name": "BLK1", "gp_name": "G", "vill_name": "V1",
         "lat": 26.5, "long": 92.0, "Dairy": 10, "Goatery": 10},
        {"district_name": "D", "block_name": "BLK2", "gp_name": "G", "vill_name": "V2",
         "lat": 26.5, "long": 92.0, "Dairy": 10, "Goatery": 10},
    ])
    monkeypatch.setattr(villages, "load_villages", lambda: df)

    class FakeCursor:
        def __init__(self):
            self._last = ""

        def execute(self, sql, params=None):
            self._last = sql

        def fetchall(self):
            # First query reads cluster_generation; second reads the locked scopes.
            return gen_rows if "cluster_generation" in self._last else locked_rows

    @contextlib.contextmanager
    def fake_get_cursor(commit=False):
        yield FakeCursor()

    monkeypatch.setattr(villages, "get_cursor", fake_get_cursor)
    # A scope is "fresh" only when its stored fingerprint equals this stub's value.
    monkeypatch.setattr(villages, "scope_fingerprint",
                        lambda b, c, p=None: "FP" if (b, c) == fresh_key else f"STALE::{b}::{c}")
    monkeypatch.setattr(villages, "coverage_summary", lambda params=None: [])

    calls = []
    monkeypatch.setattr(villages, "regenerate_clusters",
                        lambda block_name=None, commodity=None, params=None: calls.append((block_name, commodity)))
    return calls


def test_locked_scope_is_never_regenerated(monkeypatch):
    # (BLK1, Dairy) is locked (a cadre CSV edit); (BLK2, Goatery) is fresh.
    calls = _install_fakes(
        monkeypatch,
        gen_rows=[{"block_name": "BLK2", "commodity": "Goatery", "fingerprint": "FP"}],
        locked_rows=[{"block_name": "BLK1", "commodity": "Dairy"}],
        fresh_key=("BLK2", "Goatery"),
    )

    summary = villages.refresh_all_coverage()

    # The cadre-edited scope must survive untouched.
    assert ("BLK1", "Dairy") not in calls
    # The fresh scope is skipped (no needless churn).
    assert ("BLK2", "Goatery") not in calls
    # Only the stale, unlocked scopes are rebuilt.
    assert set(calls) == {("BLK1", "Goatery"), ("BLK2", "Dairy")}
    assert summary["skipped_locked"] == 1
    assert summary["fresh"] == 1
    assert summary["regenerated"] == 2
    assert summary["scopes_total"] == 4


def test_dashboard_and_finalized_scopes_are_protected(monkeypatch):
    # Every scope is protected here (locked/finalized/dashboard all funnel through
    # the same WHERE clause), so nothing should be regenerated at all.
    calls = _install_fakes(
        monkeypatch,
        gen_rows=[],
        locked_rows=[
            {"block_name": "BLK1", "commodity": "Dairy"},
            {"block_name": "BLK1", "commodity": "Goatery"},
            {"block_name": "BLK2", "commodity": "Dairy"},
            {"block_name": "BLK2", "commodity": "Goatery"},
        ],
        fresh_key=("_", "_"),
    )

    summary = villages.refresh_all_coverage()

    assert calls == []
    assert summary["skipped_locked"] == 4
    assert summary["regenerated"] == 0
