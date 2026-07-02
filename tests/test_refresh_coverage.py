"""Regression tests for the whole-state coverage refresh (villages.refresh_all_coverage)
and the coverage reconciliation (villages.coverage_summary / unmapped_blocks).

Faiz's concern (2026-07-02): the daily "run the complete thing" refresh must NOT
wipe changes made by the cadre. These tests pin that guarantee, plus the
empty-but-eligible heal and the master-block scoping, without a Postgres instance
by stubbing the DB cursor and the per-scope regen.
"""
import contextlib

import pandas as pd

import villages


def _install_fakes(monkeypatch, gen_rows, locked_rows, have_rows, fresh_key):
    """Wire villages.* so refresh_all_coverage runs against two synthetic blocks
    x two commodities with the given generation / locked / cluster-count snapshot.
    Returns the list recording every (block, commodity) handed to
    regenerate_clusters."""
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
            s = self._last
            if "cluster_generation" in s:
                return gen_rows
            if "COUNT(*)" in s and "GROUP BY block_name" in s:
                return have_rows
            return locked_rows  # the DISTINCT ... WHERE finalized OR locked ... query

    @contextlib.contextmanager
    def fake_get_cursor(commit=False):
        yield FakeCursor()

    monkeypatch.setattr(villages, "get_cursor", fake_get_cursor)
    monkeypatch.setattr(villages, "scope_fingerprint",
                        lambda b, c, p=None: "FP" if (b, c) == fresh_key else f"STALE::{b}::{c}")
    monkeypatch.setattr(villages, "coverage_summary", lambda params=None: [])

    calls = []
    monkeypatch.setattr(villages, "regenerate_clusters",
                        lambda block_name=None, commodity=None, params=None: calls.append((block_name, commodity)))
    return calls


def test_locked_scope_is_never_regenerated(monkeypatch):
    # (BLK1, Dairy) locked (cadre edit); (BLK2, Goatery) fresh AND has clusters.
    calls = _install_fakes(
        monkeypatch,
        gen_rows=[{"block_name": "BLK2", "commodity": "Goatery", "fingerprint": "FP"}],
        locked_rows=[{"block_name": "BLK1", "commodity": "Dairy"}],
        have_rows=[{"block_name": "BLK2", "commodity": "Goatery", "n": 5}],
        fresh_key=("BLK2", "Goatery"),
    )

    summary = villages.refresh_all_coverage()

    assert ("BLK1", "Dairy") not in calls          # cadre-edited scope survives
    assert ("BLK2", "Goatery") not in calls          # fresh + populated -> skipped
    assert set(calls) == {("BLK1", "Goatery"), ("BLK2", "Dairy")}
    assert summary["skipped_locked"] == 1
    assert summary["fresh"] == 1
    assert summary["regenerated"] == 2


def test_all_protected_scopes_skipped(monkeypatch):
    calls = _install_fakes(
        monkeypatch,
        gen_rows=[],
        locked_rows=[
            {"block_name": "BLK1", "commodity": "Dairy"},
            {"block_name": "BLK1", "commodity": "Goatery"},
            {"block_name": "BLK2", "commodity": "Dairy"},
            {"block_name": "BLK2", "commodity": "Goatery"},
        ],
        have_rows=[],
        fresh_key=("_", "_"),
    )
    summary = villages.refresh_all_coverage()
    assert calls == []
    assert summary["skipped_locked"] == 4
    assert summary["regenerated"] == 0


def test_empty_but_eligible_scope_is_healed_despite_fresh_fingerprint(monkeypatch):
    # (BLK1, Dairy) has a MATCHING fingerprint (would look "fresh") but ZERO
    # clusters while its data is eligible -> must be rebuilt anyway (the
    # BILASIPARA-poultry gap class). Everything else is fresh + populated.
    calls = _install_fakes(
        monkeypatch,
        gen_rows=[
            {"block_name": "BLK1", "commodity": "Dairy", "fingerprint": "FP"},
            {"block_name": "BLK1", "commodity": "Goatery", "fingerprint": "FP"},
            {"block_name": "BLK2", "commodity": "Dairy", "fingerprint": "FP"},
            {"block_name": "BLK2", "commodity": "Goatery", "fingerprint": "FP"},
        ],
        locked_rows=[],
        # every scope populated EXCEPT (BLK1, Dairy)
        have_rows=[
            {"block_name": "BLK1", "commodity": "Goatery", "n": 3},
            {"block_name": "BLK2", "commodity": "Dairy", "n": 3},
            {"block_name": "BLK2", "commodity": "Goatery", "n": 3},
        ],
        fresh_key=("*", "*"),  # force fp match for all via the stub below
    )
    # Make the fingerprint stub match for EVERY scope so only the empty-gap guard
    # can trigger a rebuild.
    monkeypatch.setattr(villages, "scope_fingerprint", lambda b, c, p=None: "FP")

    summary = villages.refresh_all_coverage()

    assert calls == [("BLK1", "Dairy")]     # only the empty-but-eligible scope
    assert summary["healed_empty"] == 1
    assert summary["regenerated"] == 1
    assert summary["fresh"] == 3


def test_coverage_summary_excludes_old_name_blocks(monkeypatch):
    # Master has only BLK1; BLK_OLD is a renamed/phantom block whose clusters must
    # NOT inflate the coverage totals (they belong in unmapped_blocks instead).
    df = pd.DataFrame([
        {"district_name": "D", "block_name": "BLK1", "gp_name": "G", "vill_name": "V1",
         "lat": 26.5, "long": 92.0, "Dairy": 100, "Goatery": 0},
    ])
    monkeypatch.setattr(villages, "load_villages", lambda: df)
    monkeypatch.setattr(villages, "COMMODITIES", ["Dairy"])

    rows = [
        {"commodity": "Dairy", "block_name": "BLK1", "clusters": 2, "assigned_members": 90},
        {"commodity": "Dairy", "block_name": "BLK_OLD", "clusters": 1, "assigned_members": 50},
    ]

    class FakeCursor:
        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return rows

    @contextlib.contextmanager
    def fake_get_cursor(commit=False):
        yield FakeCursor()

    monkeypatch.setattr(villages, "get_cursor", fake_get_cursor)

    cov = villages.coverage_summary()
    dairy = next(c for c in cov if c["commodity"] == "Dairy")
    # Only BLK1's 90 members count; BLK_OLD's 50 excluded -> assigned <= raw_total.
    assert dairy["assigned_members"] == 90
    assert dairy["raw_total_members"] == 100
    assert dairy["assigned_pct"] == 90.0
    assert dairy["blocks_with_clusters"] == 1
