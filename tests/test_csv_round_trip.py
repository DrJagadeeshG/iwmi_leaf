"""CSV download/upload schema tests covering the 9 May 2026 changes.

Verifies:
  - clusters_to_csv emits the new schema: cluster_num first, no lat/long.
  - csv_text_to_records accepts the new schema and backfills lat/long
    from the village master.
  - csv_text_to_records still accepts the legacy schema (with lat/long).
  - Unknown villages produce a clear ValueError.
"""
import io
import pandas as pd
import pytest

import villages


EXPECTED_COLUMNS = [
    "cluster_num", "cluster_id", "commodity", "district_name", "block_name",
    "gp_name", "vill_name", "members", "pashu_sakhi", "block_coordinator",
]


def test_download_schema_has_cluster_num_and_no_latlong(sample_cluster_records):
    csv_text = villages.clusters_to_csv(sample_cluster_records)
    df = pd.read_csv(io.StringIO(csv_text))
    assert list(df.columns) == EXPECTED_COLUMNS, (
        f"download schema drift: {list(df.columns)}"
    )
    assert "lat" not in df.columns and "long" not in df.columns
    # cluster_num should be the sequential 1, 2 from the fixture.
    assert df["cluster_num"].tolist() == [1, 1, 1, 1, 2]


def test_empty_clusters_still_emit_header_row():
    csv_text = villages.clusters_to_csv([])
    df = pd.read_csv(io.StringIO(csv_text))
    assert list(df.columns) == EXPECTED_COLUMNS
    assert len(df) == 0


def test_upload_backfills_latlong_from_village_master(monkeypatch, sample_cluster_records):
    """The new schema omits lat/long; csv_text_to_records must look them
    up by (block_name, vill_name) from the village master."""
    csv_text = villages.clusters_to_csv(sample_cluster_records)

    # Stub load_villages with a synthetic master that covers every village
    # in the fixture, with deterministic coordinates we can assert on.
    master = pd.DataFrame([
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": "Village_A", "gp_name": "GP-A", "lat": 26.500, "long": 92.000},
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": "Village_B", "gp_name": "GP-A", "lat": 26.510, "long": 92.005},
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": "Village_C", "gp_name": "GP-B", "lat": 26.515, "long": 92.010},
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": "Village_D", "gp_name": "GP-B", "lat": 26.495, "long": 92.012},
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": "Village_Giant", "gp_name": "GP-C", "lat": 26.600, "long": 92.200},
    ])
    monkeypatch.setattr(villages, "load_villages", lambda: master)

    records = villages.csv_text_to_records(csv_text)

    # Same number of clusters round-trip.
    assert len(records) == 2
    by_id = {r["cluster_id"]: r for r in records}
    assert "C-001" in by_id and "C-002" in by_id

    # Coordinates backfilled correctly.
    village_a = next(v for v in by_id["C-001"]["villages"]
                     if v["vill_name"] == "Village_A")
    assert village_a["lat"] == 26.500
    assert village_a["long"] == 92.000

    # Per-cluster fields survive.
    assert by_id["C-001"]["pashu_sakhi"] == "Asha"
    assert by_id["C-002"]["block_coordinator"] == "Babu"


def test_upload_still_accepts_legacy_latlong_columns(monkeypatch):
    """Legacy CSVs that include lat/long must round-trip without touching
    the village master - lat/long in the CSV wins."""
    # Sentinel coords that don't exist in any master we provide; the test
    # asserts these flow through unchanged.
    legacy_csv = (
        "cluster_id,commodity,district_name,block_name,vill_name,gp_name,"
        "lat,long,members,pashu_sakhi,block_coordinator\n"
        "C-LEGACY,Dairy,D,B,Foo,GP,1.23,4.56,30,,\n"
    )
    # Master is empty; if the loader were consulted the call would fail to
    # resolve "Foo" and raise. So a passing test proves the master is
    # bypassed when lat/long is present.
    monkeypatch.setattr(villages, "load_villages",
                        lambda: pd.DataFrame(columns=["block_name", "vill_name", "lat", "long"]))
    records = villages.csv_text_to_records(legacy_csv)
    assert len(records) == 1
    v = records[0]["villages"][0]
    assert v["lat"] == 1.23
    assert v["long"] == 4.56


def test_unknown_village_raises_with_useful_message(monkeypatch):
    """If a CSV without lat/long names a village the master doesn't
    recognise, the upload must fail fast with a message listing the row."""
    csv_text = (
        "cluster_id,commodity,district_name,block_name,vill_name,gp_name,members\n"
        "C-1,Dairy,D,B,Phantom_Village,GP,10\n"
    )
    monkeypatch.setattr(villages, "load_villages",
                        lambda: pd.DataFrame(columns=["block_name", "vill_name", "lat", "long"]))
    with pytest.raises(ValueError) as exc:
        villages.csv_text_to_records(csv_text)
    assert "Phantom_Village" in str(exc.value)


def test_cluster_num_column_in_upload_is_ignored(monkeypatch, sample_cluster_records):
    """cluster_num is display-only on download - we must not let it leak
    into stored records or affect cluster grouping."""
    csv_text = villages.clusters_to_csv(sample_cluster_records)
    master = pd.DataFrame([
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": v["vill_name"], "gp_name": v["gp_name"],
         "lat": v["lat"], "long": v["long"]}
        for c in sample_cluster_records for v in c["villages"]
    ])
    monkeypatch.setattr(villages, "load_villages", lambda: master)
    records = villages.csv_text_to_records(csv_text)
    for r in records:
        assert "cluster_num" not in r, (
            "cluster_num is a display field and must not survive into records"
        )
