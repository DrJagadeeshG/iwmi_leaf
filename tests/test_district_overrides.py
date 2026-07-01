"""Tests for block->district label overrides in data_utils.

Kamrup Metropolitan shares Kamrup's DISTRICT_I (266) in Block_assam.shp, so its
three CD blocks (Chandrapur, Dimoria, Rani/Ramcharani) are reassigned by BLOCK_ID
to "Kamrup Metro" after the DISTRICT_I->name mapping (2026-07-01).
"""
import pandas as pd

import data_utils


def test_kamrup_metro_blocks_reassigned():
    gdf = pd.DataFrame({
        "BLOCK_ID": [1166, 1636, 5087, 740, 2016],
        "Block_name": ["Chandrapur", "Dimoria", "Rani", "Bezera", "Goroimari"],
        "Dist_Name": ["Kamrup"] * 5,
    })
    out = data_utils._apply_district_overrides(gdf.copy())
    metro = set(out.loc[out["Dist_Name"] == "Kamrup Metro", "Block_name"])
    assert metro == {"Chandrapur", "Dimoria", "Rani"}
    # The Kamrup-rural blocks must be left alone.
    assert (out[out["BLOCK_ID"].isin([740, 2016])]["Dist_Name"] == "Kamrup").all()


def test_override_handles_string_block_ids():
    """BLOCK_ID can come through as strings depending on the source; the numeric
    coercion must still match."""
    gdf = pd.DataFrame({
        "BLOCK_ID": ["1166", "740"],
        "Dist_Name": ["Kamrup", "Kamrup"],
    })
    out = data_utils._apply_district_overrides(gdf)
    assert out.loc[out["BLOCK_ID"] == "1166", "Dist_Name"].iloc[0] == "Kamrup Metro"
    assert out.loc[out["BLOCK_ID"] == "740", "Dist_Name"].iloc[0] == "Kamrup"


def test_override_is_noop_without_expected_columns():
    gdf = pd.DataFrame({"foo": [1, 2]})
    out = data_utils._apply_district_overrides(gdf)  # must not raise
    assert list(out["foo"]) == [1, 2]
