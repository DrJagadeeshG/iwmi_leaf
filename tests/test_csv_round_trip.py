"""CSV download/upload schema tests.

Schema history:
  - 2026-05-09: cluster_num + cluster_id moved to front; lat/long dropped.
  - 2026-05-29 (LEAF-44): lat/long re-added so a user can append a row for a
    newly-surveyed village without that village existing in the master first.

Verifies:
  - clusters_to_csv emits the LEAF-44 schema (lat/long present).
  - csv_text_to_records accepts lat/long when present and bypasses the master.
  - csv_text_to_records still backfills lat/long from the master when the
    columns are missing (legacy CSV) - keeps old saved files importable.
  - A row that supplies lat/long for a vill_name unknown to the master is
    accepted as a new village.
  - Unknown villages WITHOUT lat/long still raise a clear ValueError.
"""
import io
import pandas as pd
import pytest

import villages


EXPECTED_COLUMNS = [
    "cluster_code", "cluster_name", "cluster_num", "cluster_id", "commodity", "district_name",
    "block_name", "gp_name", "vill_name", "lat", "long", "members", "pashu_sakhi",
    "block_coordinator", "district_coordinator",
]


def test_download_schema_has_cluster_num_and_latlong(sample_cluster_records):
    csv_text = villages.clusters_to_csv(sample_cluster_records)
    df = pd.read_csv(io.StringIO(csv_text))
    assert list(df.columns) == EXPECTED_COLUMNS, (
        f"download schema drift: {list(df.columns)}"
    )
    assert "lat" in df.columns and "long" in df.columns
    # cluster_num should be the sequential 1, 2 from the fixture.
    assert df["cluster_num"].tolist() == [1, 1, 1, 1, 2]
    # Lat/long must be populated for every row, not null.
    assert df["lat"].notna().all() and df["long"].notna().all()


def test_upload_accepts_new_village_via_csv_latlong(monkeypatch):
    """LEAF-44: a row that names a vill_name unknown to the master but
    supplies its own lat/long must round-trip as a new village instead of
    failing with the 'could not resolve' error."""
    csv_text = (
        "cluster_id,commodity,district_name,block_name,vill_name,gp_name,"
        "lat,long,members,pashu_sakhi,block_coordinator\n"
        "C-1,Dairy,D,B,KnownVill,GP,1.0,2.0,30,,\n"
        "C-1,Dairy,D,B,FieldSurveyed,GP,1.01,2.01,12,,\n"
    )
    # Master only has KnownVill - FieldSurveyed is brand new from the field.
    monkeypatch.setattr(villages, "load_villages", lambda: pd.DataFrame([
        {"district_name": "D", "block_name": "B", "vill_name": "KnownVill",
         "gp_name": "GP", "lat": 1.0, "long": 2.0},
    ]))
    records = villages.csv_text_to_records(csv_text)
    assert len(records) == 1
    villages_in = records[0]["villages"]
    assert {v["vill_name"] for v in villages_in} == {"KnownVill", "FieldSurveyed"}
    new = next(v for v in villages_in if v["vill_name"] == "FieldSurveyed")
    assert new["lat"] == 1.01 and new["long"] == 2.01


def test_empty_clusters_still_emit_header_row():
    csv_text = villages.clusters_to_csv([])
    df = pd.read_csv(io.StringIO(csv_text))
    assert list(df.columns) == EXPECTED_COLUMNS
    assert len(df) == 0


def test_upload_round_trips_latlong_via_csv(monkeypatch, sample_cluster_records):
    """LEAF-44: lat/long is round-tripped through the CSV; the master is not
    consulted when lat/long is present in the row."""
    csv_text = villages.clusters_to_csv(sample_cluster_records)

    # Master deliberately empty - if the parser consulted it instead of the
    # CSV's lat/long, every village would land in `missing` and raise.
    monkeypatch.setattr(villages, "load_villages",
                        lambda: pd.DataFrame(columns=["block_name", "vill_name", "lat", "long"]))

    records = villages.csv_text_to_records(csv_text)

    assert len(records) == 2
    by_id = {r["cluster_id"]: r for r in records}
    assert "C-001" in by_id and "C-002" in by_id

    # Coordinates from the CSV survive byte-for-byte.
    village_a = next(v for v in by_id["C-001"]["villages"]
                     if v["vill_name"] == "Village_A")
    assert village_a["lat"] == 26.500
    assert village_a["long"] == 92.000

    # Per-cluster fields survive.
    assert by_id["C-001"]["pashu_sakhi"] == "Asha"
    assert by_id["C-002"]["block_coordinator"] == "Babu"


def test_upload_backfills_latlong_from_master_when_columns_missing(monkeypatch):
    """Legacy CSVs (no lat/long columns at all) must still import by looking
    the coords up from the master - keeps older saved files importable."""
    legacy_csv_no_coords = (
        "cluster_id,commodity,district_name,block_name,vill_name,gp_name,members\n"
        "C-1,Dairy,TESTDIST,TESTBLK,Village_A,GP-A,10\n"
    )
    master = pd.DataFrame([
        {"district_name": "TESTDIST", "block_name": "TESTBLK",
         "vill_name": "Village_A", "gp_name": "GP-A", "lat": 26.500, "long": 92.000},
    ])
    monkeypatch.setattr(villages, "load_villages", lambda: master)
    records = villages.csv_text_to_records(legacy_csv_no_coords)
    v = records[0]["villages"][0]
    assert v["lat"] == 26.500 and v["long"] == 92.000


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


def test_cluster_name_round_trips_and_blank_parses_none(monkeypatch, sample_cluster_records):
    """cluster_name is an editable display-name override for cluster_code: a
    custom value must survive clusters_to_csv -> csv_text_to_records, and a
    blank/whitespace cell must parse back to None so the auto code is kept."""
    # C-001 gets a custom name; C-002 is left blank.
    recs = [dict(c) for c in sample_cluster_records]
    recs[0]["cluster_name"] = "Faiz Dairy Hub"
    recs[1]["cluster_name"] = "   "  # whitespace-only -> must become None

    csv_text = villages.clusters_to_csv(recs)
    df = pd.read_csv(io.StringIO(csv_text))
    assert "cluster_name" in df.columns
    # Exported value is the custom name for C-001.
    c1_rows = df[df["cluster_id"] == "C-001"]
    assert (c1_rows["cluster_name"] == "Faiz Dairy Hub").all()

    # CSV's lat/long present, so the master is not consulted.
    monkeypatch.setattr(villages, "load_villages",
                        lambda: pd.DataFrame(columns=["block_name", "vill_name", "lat", "long"]))
    records = villages.csv_text_to_records(csv_text)
    by_id = {r["cluster_id"]: r for r in records}
    assert by_id["C-001"]["cluster_name"] == "Faiz Dairy Hub"
    # Whitespace-only / blank -> None (auto cluster_code kept downstream).
    assert by_id["C-002"]["cluster_name"] is None


def test_cluster_name_absent_column_imports_as_none(monkeypatch):
    """Older CSVs predating cluster_name (no such column) still import, with
    cluster_name left None."""
    legacy_csv = (
        "cluster_id,commodity,district_name,block_name,vill_name,gp_name,"
        "lat,long,members\n"
        "C-1,Dairy,D,B,Foo,GP,1.23,4.56,30\n"
    )
    monkeypatch.setattr(villages, "load_villages",
                        lambda: pd.DataFrame(columns=["block_name", "vill_name", "lat", "long"]))
    records = villages.csv_text_to_records(legacy_csv)
    assert records[0]["cluster_name"] is None


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
