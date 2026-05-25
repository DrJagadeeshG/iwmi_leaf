"""Guardrail validation tests (LEAF-60).

Exercises google_sheets.validate_sheets() against synthetic good/bad sheets by
monkeypatching get_sheet, so no network or Postgres is required.
"""
import pandas as pd
import google_sheets as gs


def _patch(monkeypatch, dss_input, block_values):
    def fake_get_sheet(key):
        return {"dss_input": dss_input, "block_values": block_values}.get(key)
    monkeypatch.setattr(gs, "get_sheet", fake_get_sheet)


def _good_block_values():
    return pd.DataFrame({
        "BLOCK_ID": [1, 2], "STATE_ID": [18, 18], "DISTRICT_I": [1, 1],
        "id": [1, 2], "Block_name": ["Alpha", "Beta"],
        "BF": [10, 20], "Dist_Name": ["D1", "D1"],
    })


def _good_dss_input():
    return pd.DataFrame({
        "Cluster": ["Organic Farming", "Organic Farming"],
        "I_variable": ["BF", "BF"],
        "range_min": [10, 0], "range_max": [50, 100],
    })


def test_clean_sheets_pass(monkeypatch):
    _patch(monkeypatch, _good_dss_input(), _good_block_values())
    result = gs.validate_sheets()
    assert result["ok"] is True
    assert result["issues"] == []


def test_duplicate_block_id_is_error(monkeypatch):
    bv = _good_block_values()
    bv.loc[1, "BLOCK_ID"] = 1  # duplicate
    _patch(monkeypatch, _good_dss_input(), bv)
    result = gs.validate_sheets()
    assert result["ok"] is False
    assert any(i["severity"] == "error" and "Duplicate BLOCK_ID" in i["message"] for i in result["issues"])


def test_missing_id_column_is_error(monkeypatch):
    bv = _good_block_values().drop(columns=["Block_name"])
    _patch(monkeypatch, _good_dss_input(), bv)
    result = gs.validate_sheets()
    assert result["ok"] is False
    assert any("Block_name" in i["message"] for i in result["issues"])


def test_range_min_gt_max_is_error(monkeypatch):
    di = _good_dss_input()
    di.loc[0, "range_min"] = 99  # min > max (50)
    _patch(monkeypatch, di, _good_block_values())
    result = gs.validate_sheets()
    assert result["ok"] is False
    assert any("range_min greater than range_max" in i["message"] for i in result["issues"])


def test_unknown_variable_code_is_warning(monkeypatch):
    di = _good_dss_input()
    di.loc[0, "I_variable"] = "ZZZ"  # not a block_values column
    _patch(monkeypatch, di, _good_block_values())
    result = gs.validate_sheets()
    assert any(i["severity"] == "warning" and "ZZZ" in i["message"] for i in result["issues"])


def test_stray_text_in_numeric_column_is_warning(monkeypatch):
    bv = _good_block_values()
    bv["BF"] = [10, "oops"]  # mostly numeric, one stray text cell
    _patch(monkeypatch, _good_dss_input(), bv)
    result = gs.validate_sheets()
    assert any(i["severity"] == "warning" and "non-numeric" in i["message"].lower() for i in result["issues"])
