"""Shared fixtures for leaf_flask tests.

Keeps the test suite focused on pure functions where possible so a Postgres
instance isn't required to verify the algorithm and CSV helpers. The Flask
app is imported lazily inside the admin-guard tests so import-time
side effects (DB pool creation) don't break the rest of the suite.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make the leaf_flask package importable as flat modules (matches how the
# app itself imports them, e.g. `import clustering`).
PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


@pytest.fixture
def sample_villages_df():
    """Synthetic block with enough villages to exercise the clustering rules.

    Layout (Dairy member counts shown):
      - 4 dairy villages tightly clustered around (26.50, 92.00) -> normal cluster
      - 1 dairy village far away with 200 members -> single-village cluster (#18)
      - 1 dairy village isolated with 5 members -> orphan that should be
        merged into the tight cluster (#19) since it sits within 2x radius.
    """
    rows = [
        # Tight cluster of 4 villages (small dairy counts add up to band)
        {"district_name": "TESTDIST", "block_name": "TESTBLK", "gp_name": "GP-A",
         "vill_name": "Village_A", "lat": 26.500, "long": 92.000, "Dairy": 10},
        {"district_name": "TESTDIST", "block_name": "TESTBLK", "gp_name": "GP-A",
         "vill_name": "Village_B", "lat": 26.510, "long": 92.005, "Dairy": 9},
        {"district_name": "TESTDIST", "block_name": "TESTBLK", "gp_name": "GP-B",
         "vill_name": "Village_C", "lat": 26.515, "long": 92.010, "Dairy": 8},
        {"district_name": "TESTDIST", "block_name": "TESTBLK", "gp_name": "GP-B",
         "vill_name": "Village_D", "lat": 26.495, "long": 92.012, "Dairy": 7},
        # Standalone giant - 200 members, must trigger single-village exception
        {"district_name": "TESTDIST", "block_name": "TESTBLK", "gp_name": "GP-C",
         "vill_name": "Village_Giant", "lat": 26.600, "long": 92.200, "Dairy": 200},
        # Orphan near the tight cluster (within 2x default 5km radius)
        {"district_name": "TESTDIST", "block_name": "TESTBLK", "gp_name": "GP-A",
         "vill_name": "Village_Orphan", "lat": 26.540, "long": 92.030, "Dairy": 3},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def sample_cluster_records():
    """Two clusters worth of rows for CSV round-trip tests."""
    return [
        {
            "cluster_id": "C-001",
            "cluster_num": 1,
            "commodity": "Dairy",
            "district_name": "TESTDIST",
            "block_name": "TESTBLK",
            "total_members": 34,
            "max_span_km": 1.2,
            "centroid_lat": 26.505,
            "centroid_lon": 92.007,
            "pashu_sakhi": "Asha",
            "block_coordinator": None,
            "villages": [
                {"vill_name": "Village_A", "gp_name": "GP-A",
                 "lat": 26.500, "long": 92.000, "members": 10},
                {"vill_name": "Village_B", "gp_name": "GP-A",
                 "lat": 26.510, "long": 92.005, "members": 9},
                {"vill_name": "Village_C", "gp_name": "GP-B",
                 "lat": 26.515, "long": 92.010, "members": 8},
                {"vill_name": "Village_D", "gp_name": "GP-B",
                 "lat": 26.495, "long": 92.012, "members": 7},
            ],
        },
        {
            "cluster_id": "C-002",
            "cluster_num": 2,
            "commodity": "Dairy",
            "district_name": "TESTDIST",
            "block_name": "TESTBLK",
            "total_members": 200,
            "max_span_km": 0.0,
            "centroid_lat": 26.600,
            "centroid_lon": 92.200,
            "pashu_sakhi": None,
            "block_coordinator": "Babu",
            "villages": [
                {"vill_name": "Village_Giant", "gp_name": "GP-C",
                 "lat": 26.600, "long": 92.200, "members": 200},
            ],
        },
    ]
