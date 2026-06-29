"""
Build data/villages.csv from the client SHG survey workbook.

The village master is the cluster-planner's source of truth: the app reads
district / block / village and the per-village commodity member counts straight
from this CSV (villages.list_blocks_with_villages, aggregate_villages,
block_shg_summary, villages_geojson). So the District -> Block -> Village
hierarchy and counts shown in the tool are EXACTLY what this file writes.

Source format (SHG_Assam_Consolidated_final_Jun22, Jun 2026)
------------------------------------------------------------
This consolidated export has NO pre-computed `LEAF Block` / `LEAF District`
columns; block / district come straight from the survey's own `Block` /
`District`. Activity columns use verbose labels ("Number of SHG members
engaged in dairy production").

Naming is SOURCE-AUTHORITATIVE (2026-06-29)
-------------------------------------------
district_name / block_name are taken verbatim from the survey's District /
Block columns (uppercased, internal whitespace collapsed). They are NOT
rewritten against the block shapefile.

History / why this changed: an earlier version of this script overrode the
district from a block shapefile (`canonical_block_district`) and routed any
block whose name didn't match the shapefile through a point-in-polygon
"recovery" that reassigned the village to whichever old polygon contained it.
Because that shapefile predates the newer districts (e.g. BAJALI, carved out
of BARPETA) and uses different block spellings, it silently moved villages to
the wrong district, renamed blocks, merged them, and changed per-block counts
(Faiz, 2026-06-29: "the data is not being reflected ... the name of the block
is also not correct ... systematic error"). The shapefile is the right key for
the *map / feasibility* layer, but the cluster planner must mirror the sheet,
so block/district names here now come straight from the survey.

Pipeline
--------
  - Coordinates: numeric, sanity-checked against the Assam bounding box. Rows
    with missing / non-numeric / out-of-range coordinates are dropped (they
    can't be placed on the map or clustered) and reported individually so the
    client can correct them in the source sheet. This is the ONLY reason a row
    is dropped, so per-block counts match the sheet barring genuine coordinate
    errors.
  - district_name / block_name: survey District / Block, upper + whitespace-
    collapsed. Verbatim.
  - Commodities: the survey activity columns map 1:1 to the Kobo snake_case
    keys, then aggregate into the 6 clustering commodities exactly as
    ingest_kobo.COMMODITY_BUCKETS does. Feed / Fodder / Livestock transport /
    Meat shop (and the other non-clustering activities) are surfaced under the
    "other activities" columns, not the 6 commodity buckets.

Note: a handful of block names repeat across two districts in the source
(e.g. GOBARDHANA in BAKSA and BARPETA). They are kept distinct here by their
(district, block) pair, as the sheet has them.

Usage:
    $env:PYTHONUTF8=1
    python scripts/build_village_master.py            # write data/villages.csv
    python scripts/build_village_master.py --dry-run   # report only, no write
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
# Raw client survey workbook. Lives in source_data/ (gitignored — it carries
# enumerator PII); only the derived data/villages.csv is committed.
SURVEY_XLSX = REPO / "source_data" / "SHG_Assam_Consolidated_final_Jun22.xlsx"
SURVEY_SHEET = "Village Location Detail"
VILLAGES_CSV = DATA / "villages.csv"

# Assam bounding box (drop rows whose coordinates fall outside it).
LAT_MIN, LAT_MAX = 24.0, 28.5
LON_MIN, LON_MAX = 89.5, 96.5

# Survey verbose activity column -> Kobo snake_case key (ingest_kobo names).
SURVEY_TO_KOBO = {
    "Number of SHG members engaged in dairy production": "dairy_production",
    "Number of SHG members engaged in goat farming or production": "goat_farming",
    "Number of SHG members engaged in goat breeding farm": "goat_breeding_farm",
    "Number of SHG members engaged in kid nursery for goat": "goat_kid_nursery",
    "Number of SHG members engaged in pig farming or production": "pig_farming",
    "Number of SHG members engaged in pig breeding farm": "pig_breeding_farm",
    "Number of SHG members engaged in piglet nursery for pig": "pig_piglet_nursery",
    "Number of SHG members engaged in backyard poultry farming or production": "poultry_backyard",
    "Number of SHG members engaged in broiler rearing or production": "poultry_broiler",
    "Number of SHG members engaged in hatchery unit for poultry and duck": "poultry_duck_hatchery",
    "Number of SHG members engaged in duck rearing or production": "duck_rearing",
    "Number of SHG members engaged in fishery activity or production": "fishery_activity",
    "Number of SHG members engaged in hatchery unit for fishery": "fishery_hatchery",
    "Number of SHG members engaged in fishing equipment trading": "fishery_equip_trading",
    "Number of SHG members engaged in fishing equipment lending": "fishery_equip_lending",
    "Number of SHG members engaged in fishing equipment manufacturing": "fishery_equip_mfg",
    "Number of SHG members engaged in fish trading": "fish_trading",
    # Excluded from the 6 commodities (surfaced under OTHER_BUCKETS instead):
    # "...feed manufacturing or production unit", "...fodder cultivation or production",
    # "...livestock transportation", "...meat shop"
}

# Aggregation into the 6 clustering commodities (== ingest_kobo.COMMODITY_BUCKETS,
# minus the v2-only keys that don't exist in the survey).
COMMODITY_BUCKETS = {
    "Dairy": ["dairy_production"],
    "Goatery": ["goat_farming", "goat_breeding_farm", "goat_kid_nursery"],
    "Piggery": ["pig_farming", "pig_breeding_farm", "pig_piglet_nursery"],
    "Backyard_Poultry": ["poultry_backyard", "poultry_broiler", "poultry_duck_hatchery"],
    "Duckery": ["duck_rearing"],
    "Fishery_Activity": [
        "fishery_activity", "fishery_hatchery", "fishery_equip_trading",
        "fishery_equip_lending", "fishery_equip_mfg", "fish_trading",
    ],
}

# "Other" livelihood activities outside the 6 clustering commodities. Output
# column names match villages._OTHER_KEYS labels exactly. Each maps to its
# verbose survey column.
OTHER_BUCKETS = {
    "Fodder cultivation": ["Number of SHG members engaged in fodder cultivation or production"],
    "Feed manufacturing": ["Number of SHG members engaged in feed manufacturing or production unit"],
    "Livestock transport": ["Number of SHG members engaged in livestock transportation"],
    "Meat shop": ["Number of SHG members engaged in meat shop"],
    "Goat breeding farm": ["Number of SHG members engaged in goat breeding farm"],
    "Kid nursery for goat": ["Number of SHG members engaged in kid nursery for goat"],
    "Pig breeding farm": ["Number of SHG members engaged in pig breeding farm"],
    "Piglet nursery for pig": ["Number of SHG members engaged in piglet nursery for pig"],
    "Hatchery (poultry & duck)": ["Number of SHG members engaged in hatchery unit for poultry and duck"],
    "Hatchery for fishery": ["Number of SHG members engaged in hatchery unit for fishery"],
    "Fishing equipment trading": ["Number of SHG members engaged in fishing equipment trading"],
    "Fishing equipment lending": ["Number of SHG members engaged in fishing equipment lending"],
    "Fishing equipment manufacturing": ["Number of SHG members engaged in fishing equipment manufacturing"],
    "Fish trading": ["Number of SHG members engaged in fish trading"],
}

OUTPUT_COLUMNS = [
    "district_name", "block_name", "gp_name", "vill_name", "lat", "long",
    "Dairy", "Goatery", "Piggery", "Backyard_Poultry", "Duckery", "Fishery_Activity",
] + list(OTHER_BUCKETS.keys())

# Curated block-name typo corrections (CLIENT DATA, 2026-06-29). Each LHS is a
# misspelled stray that fragments a real block in the SAME district off its
# dominant spelling (RHS) — found by a within-district near-duplicate scan and
# verified one-by-one. This is NOT fuzzy matching: directional splits that look
# similar but are real distinct blocks (DERGAON NORTH/SOUTH, GOLAGHAT EAST/WEST)
# are deliberately NOT here. Applied after the generic " BLOCK"/punctuation
# cleanup. These are also flagged to the client to fix at source.
#   typo (district, villages)            -> correct spelling (villages)
BLOCK_TYPO_FIXES = {
    "MURKNGSELEK TRIBAL": "MURKONGSELEK TRIBAL",  # DHEMAJI   (1 -> 326)
    "BINAKANDI": "BINNAKANDI",                    # HOJAI     (20 -> 91)
    "BINNAKANDIM": "BINNAKANDI",                  # HOJAI     (1 -> 91)
    "HATIDURA": "HATIDHURA",                       # KOKRAJHAR (11 -> 142)
    "GHILAMSRA": "GHILAMARA",                      # LAKHIMPUR (1 -> 95)
    "PATHAR KANDHI": "PATHARKANDI",                # SRIBHUMI  (1 -> 68)
}


def clean_block(s):
    """Block name from the survey: upper + whitespace-collapsed, with a trailing
    ' BLOCK' word and trailing punctuation removed (formatting noise in the
    source), then curated typo corrections applied. Meaning-preserving — it only
    merges spellings that denote the same block."""
    b = upper_strip(s)
    b = re.sub(r"\s+BLOCK$", "", b).rstrip(". ").strip()
    return BLOCK_TYPO_FIXES.get(b, b)


def to_int(v):
    try:
        if v is None or pd.isna(v):
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def upper_strip(s):
    if pd.isna(s):
        return ""
    # Collapse internal whitespace/newlines so the row-per-village cluster CSV
    # download/upload stays clean.
    return " ".join(str(s).split()).upper()


def survey_to_out(df):
    """Build the output frame (names + numeric coords + 6 commodities + other
    activities) from the survey sub-frame. district_name / block_name are taken
    verbatim from the survey columns. Commodity aggregation is identical to
    ingest_kobo."""
    out = pd.DataFrame({
        "district_name": df["District"].map(upper_strip),
        "block_name": df["Block"].map(clean_block),
        "gp_name": df["Gaon Panchayat"].map(upper_strip),
        "vill_name": df["Village"].map(upper_strip),
        "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
        "long": pd.to_numeric(df["Longitude"], errors="coerce"),
    })
    kobo = pd.DataFrame(index=df.index)
    for survey_col, key in SURVEY_TO_KOBO.items():
        kobo[key] = df[survey_col].map(to_int)
    for commodity, keys in COMMODITY_BUCKETS.items():
        out[commodity] = kobo[keys].sum(axis=1).astype(int)
    for label, survey_cols in OTHER_BUCKETS.items():
        out[label] = pd.concat(
            [df[c].map(to_int) for c in survey_cols], axis=1
        ).sum(axis=1).astype(int)
    return out[OUTPUT_COLUMNS].reset_index(drop=True)


def build(dry_run: bool = False) -> int:
    print(f"Reading {SURVEY_XLSX} :: {SURVEY_SHEET}")
    df = pd.read_excel(SURVEY_XLSX, sheet_name=SURVEY_SHEET)
    n0 = len(df)
    print(f"Source rows: {n0}")

    # Verify expected columns exist (verbose activity schema + the name/coord cols).
    missing_cols = [c for c in SURVEY_TO_KOBO if c not in df.columns]
    missing_cols += [c for cols in OTHER_BUCKETS.values() for c in cols if c not in df.columns]
    for c in ["District", "Block", "Gaon Panchayat", "Village", "Latitude", "Longitude"]:
        if c not in df.columns:
            missing_cols.append(c)
    if missing_cols:
        print("\n!! MISSING expected columns in source workbook:")
        for c in missing_cols:
            print(f"     {c!r}")
        print("   (column labels may have changed — update SURVEY_TO_KOBO / OTHER_BUCKETS)")
        return 1

    # Coordinate sanity — the ONLY drop reason. Everything else is kept verbatim
    # so the per-block counts match the sheet.
    df = df.copy()
    lat = pd.to_numeric(df["Latitude"], errors="coerce")
    lon = pd.to_numeric(df["Longitude"], errors="coerce")
    coord_na = lat.isna() | lon.isna()
    in_range = lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX)
    bad_coord = coord_na | ~in_range
    dropped = df[bad_coord]
    df = df[~bad_coord].copy()

    out = survey_to_out(df)

    # ---- Report ----
    print("\n=== ROW ACCOUNTING ===")
    print(f"  source rows                          : {n0}")
    print(f"  dropped: missing/non-numeric coords  : {int(coord_na.sum())}")
    print(f"  dropped: out-of-range (Assam bbox)   : {int((~coord_na & ~in_range).sum())}")
    print(f"  final rows                           : {len(out)}")

    if len(dropped):
        print("\n=== DROPPED ROWS (coordinate errors — fix in source sheet) ===")
        cols = ["District", "Block", "Gaon Panchayat", "Village", "Latitude", "Longitude"]
        for _, r in dropped[cols].iterrows():
            print(f"  {r['District']} / {r['Block']} / {r['Gaon Panchayat']} / "
                  f"{r['Village']}  ({r['Latitude']}, {r['Longitude']})")

    print("\n=== COVERAGE (== source sheet) ===")
    print(f"  districts            : {out['district_name'].nunique()}")
    print(f"  (district,block) pairs: {out.groupby(['district_name','block_name']).ngroups}")
    print(f"  distinct block names : {out['block_name'].nunique()}")

    # Block names appearing in more than one district (kept distinct here).
    multi = (
        out.groupby("block_name")["district_name"].nunique()
        .pipe(lambda s: s[s > 1])
    )
    if len(multi):
        print(f"\n  block names spanning >1 district (kept per source): {len(multi)}")
        for b in multi.index:
            counts = out[out["block_name"] == b].groupby("district_name").size().to_dict()
            print(f"     {b:20s} {counts}")

    # ---- Continuity vs the previous villages.csv ----
    if VILLAGES_CSV.exists():
        old = pd.read_csv(VILLAGES_CSV)
        old_counts = old.groupby(old["block_name"].str.upper()).size()
        new_counts = out.groupby("block_name").size()
        print("\n=== CONTINUITY vs previous villages.csv ===")
        print(f"  previous rows: {len(old)}  blocks: {old['block_name'].str.upper().nunique()}")
        print(f"  new rows     : {len(out)}  blocks: {out['block_name'].nunique()}")
        gained = sorted(set(new_counts.index) - set(old_counts.index))
        lost = sorted(set(old_counts.index) - set(new_counts.index))
        if gained:
            print(f"  block names newly present ({len(gained)}): {', '.join(gained[:25])}"
                  + (" ..." if len(gained) > 25 else ""))
        if lost:
            print(f"  block names no longer present ({len(lost)}): {', '.join(lost[:25])}"
                  + (" ..." if len(lost) > 25 else ""))

    if dry_run:
        print("\n[dry-run] not writing.")
        return 0

    out.to_csv(VILLAGES_CSV, index=False, encoding="utf-8")
    print(f"\nWrote {VILLAGES_CSV} : {len(out)} rows, "
          f"{out['block_name'].nunique()} distinct block names, "
          f"{out['district_name'].nunique()} districts.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return build(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
