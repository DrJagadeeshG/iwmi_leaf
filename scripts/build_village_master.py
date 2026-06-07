"""
Build data/villages.csv from the client SHG survey workbook.

Replaces the 14-block seed village master with the full client survey
(`Village Location Detail` sheet), expanding cluster-planning coverage to all
LEAF blocks that match the block shapefile (data/4DSS_VAR_2.0.shp Block_name).

Pipeline (mirrors ingest_kobo.py commodity semantics 1:1):
  - Drop the single junk row (Location Status == 'Column5').
  - Drop 'Location Missing' rows (no coordinates -> can't cluster).
  - KEEP '<20m GPS Cluster' rows (real, co-located villages).
  - Drop 'LEAF Block' == '— no match' rows (belong to non-LEAF blocks).
  - Names: LEAF District -> district_name, LEAF Block -> block_name,
    Gaon Panchayat -> gp_name, Village -> vill_name, all UPPER-cased to match
    the existing villages.csv convention.
  - Apply BLOCK_NAME_FIXES (survey spelling -> shapefile-canonical UPPER name)
    so every block matches data/4DSS_VAR_2.0.shp (case-insensitive; the app
    title-cases for display). Each mapping is a verified spelling variant.
  - Coordinates: numeric, sanity-clamped to the Assam bounding box; out-of-range
    rows are dropped.
  - Commodities: the survey's Title-Case activity columns map 1:1 to the Kobo
    snake_case keys, then aggregate into the 6 clustering commodities exactly as
    ingest_kobo.COMMODITY_BUCKETS does. Feed / Fodder / Livestock transport /
    Meat shop are excluded (same as ingest_kobo).

Usage:
    $env:PYTHONUTF8=1
    python scripts/build_village_master.py            # write data/villages.csv
    python scripts/build_village_master.py --dry-run   # report only, no write
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
SURVEY_XLSX = Path(r"C:\Users\sindh\Downloads\SHG_Assam_June2_WithLEAF.xlsx")
SURVEY_SHEET = "Village Location Detail"
VILLAGES_CSV = DATA / "villages.csv"
SHP_4DSS = DATA / "4DSS_VAR_2.0.shp"

NO_MATCH = "— no match"

# Assam bounding box (per task spec).
LAT_MIN, LAT_MAX = 24.0, 28.5
LON_MIN, LON_MAX = 89.5, 96.5

# Survey Title-Case activity column -> Kobo snake_case key (ingest_kobo names).
# The survey has no separate goat_nursery / pig_nursery / poultry_hen /
# fishery_nursery_pond columns (Kobo v2 variants), so those simply don't appear.
SURVEY_TO_KOBO = {
    "Dairy Production": "dairy_production",
    "Goat Farming Or Production": "goat_farming",
    "Goat Breeding Farm": "goat_breeding_farm",
    "Kid Nursery For Goat": "goat_kid_nursery",
    "Pig Farming Or Production": "pig_farming",
    "Pig Breeding Farm": "pig_breeding_farm",
    "Piglet Nursery For Pig": "pig_piglet_nursery",
    "Backyard Poultry Farming Or Production": "poultry_backyard",
    "Broiler Rearing Or Production": "poultry_broiler",
    "Hatchery Unit For Poultry And Duck": "poultry_duck_hatchery",
    "Duck Rearing Or Production": "duck_rearing",
    "Fishery Activity Or Production": "fishery_activity",
    "Hatchery Unit For Fishery": "fishery_hatchery",
    "Fishing Equipment Trading": "fishery_equip_trading",
    "Fishing Equipment Lending": "fishery_equip_lending",
    "Fishing Equipment Manufacturing": "fishery_equip_mfg",
    "Fish Trading": "fish_trading",
    # Excluded (ingest_kobo does NOT bucket these into the 6 commodities):
    # "Feed Manufacturing Or Production Unit": feed_manufacturing,
    # "Fodder Cultivation Or Production":      fodder_cultivation,
    # "Livestock Transportation":             livestock_transport,
    # "Meat Shop":                            meat_shop,
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

# Survey LEAF Block spelling (UPPER) -> shapefile-canonical Block_name (UPPER).
# Every value is verified present in data/4DSS_VAR_2.0.shp Block_name. These are
# spelling variants only; no two survey blocks collide onto one shapefile block.
# NOTE: SIDLI-CHIRANG is split into "SIDLI CHIRANG I"/"II" in the shapefile; the
# survey carries a single block so we map it to "SIDLI CHIRANG I" (the primary
# polygon). Flagged for the client to refine if they want the II split.
BLOCK_NAME_FIXES = {
    "AGOMANI": "AGOMONI",
    "BAGHMARA": "BAGHMORA",
    "BARBARUAH": "BORBARUA",
    "BARKHETRI": "BORKHETRI",
    "BASKA": "BAKSA",
    "BIHDIA -JAJIKONA": "BIHDIA JAJIKONA",
    "BOGINADI": "BOGINODI",
    "BOROBAZAR": "BOROBAJAR",
    "CHAYANI": "CHAYANI BORDUAR",
    "DALGAON-SIALMARI": "DALGAON SIALMARI",
    "DOTMA": "DOTOMA",
    "DULLAVCHERRA": "DULLAV CHERRA",
    "GAURISAGAR": "GAURI SAGAR",
    "GOMAPHULBARI": "GAMA-FULBARI",
    "GOMARIGURI": "GAMARIGURI",
    "JALESWAR": "JOLESHWAR",
    "KALIABOR": "KALIABAR",
    "KAPILI": "KOPILI",
    "KATHIATOLI": "KATHIATALI",
    "LAHARIGHAT": "LAHORIGHAT",
    "LAKUWA": "LAKWA",
    "MURKONGSELEK": "MURKONGSELLEK",
    "NORTH WEST JORHAT": "JORHAT NORTH WEST",
    "PACHIM KALIABOR": "PASCHIM KALIABAR",
    "PAKABETBARI": "PAKA-BETBARI",
    "PAKHIMORIA": "PAKHIMARIA",
    "PUB-MANGALDAI": "PUB MANGALDOI",
    "ROWTA": "ROWTA CHARALI",
    "SIDLI-CHIRANG": "SIDLI CHIRANG I",
    "SOOTEA": "SOOTIA",
    "TAPATTARY": "TAPATTARI",
}

OUTPUT_COLUMNS = [
    "district_name", "block_name", "gp_name", "vill_name", "lat", "long",
    "Dairy", "Goatery", "Piggery", "Backyard_Poultry", "Duckery", "Fishery_Activity",
]


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
    # Collapse any internal whitespace/newlines (some survey names carry embedded
    # line breaks) so the row-per-village cluster CSV download/upload stays clean.
    return " ".join(str(s).split()).upper()


def build(dry_run: bool = False) -> int:
    print(f"Reading {SURVEY_XLSX} :: {SURVEY_SHEET}")
    df = pd.read_excel(SURVEY_XLSX, sheet_name=SURVEY_SHEET)
    n0 = len(df)
    print(f"Source rows: {n0}")

    acct = {}

    # 1. Drop junk row.
    junk = df["Location Status"].astype(str) == "Column5"
    acct["junk (Location Status=='Column5')"] = int(junk.sum())
    df = df[~junk]

    # 2. Drop LEAF Block '— no match' (and any NaN LEAF Block).
    lb = df["LEAF Block"]
    nomatch = lb.isna() | (lb.astype(str).str.strip() == NO_MATCH)
    nm_view = df[nomatch]
    acct["LEAF Block '— no match' / blank"] = int(nomatch.sum())
    # Report top unmatched ODK blocks for the client.
    odk_col = "ODK Block (Standardised)"
    top_unmatched = (
        nm_view[odk_col].astype(str).str.strip().replace("", pd.NA).dropna()
        .value_counts().head(15)
    )
    df = df[~nomatch]

    # 3. Drop 'Location Missing' (no coordinates). KEEP '<20m GPS Cluster'.
    loc_missing = df["Action Required"].astype(str).str.strip() == "Location Missing"
    acct["Action Required == 'Location Missing'"] = int(loc_missing.sum())
    df = df[~loc_missing]

    # 4. Build output frame with names.
    out = pd.DataFrame({
        "district_name": df["LEAF District"].map(upper_strip),
        "block_name": df["LEAF Block"].map(upper_strip),
        "gp_name": df["Gaon Panchayat"].map(upper_strip),
        "vill_name": df["Village"].map(upper_strip),
        "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
        "long": pd.to_numeric(df["Longitude"], errors="coerce"),
    })

    # 4a. Apply block-name spelling fixes -> shapefile-canonical.
    out["block_name"] = out["block_name"].replace(BLOCK_NAME_FIXES)

    # 5. Commodity aggregation (1:1 survey -> kobo key, then bucket).
    kobo = pd.DataFrame(index=df.index)
    for survey_col, key in SURVEY_TO_KOBO.items():
        kobo[key] = df[survey_col].map(to_int)
    for commodity, keys in COMMODITY_BUCKETS.items():
        out[commodity] = kobo[keys].sum(axis=1).astype(int)

    # 6. Coordinate sanity (drop missing + out-of-Assam-range).
    coord_na = out["lat"].isna() | out["long"].isna()
    acct["missing numeric lat/long"] = int(coord_na.sum())
    out = out[~coord_na]
    in_range = (
        out["lat"].between(LAT_MIN, LAT_MAX) & out["long"].between(LON_MIN, LON_MAX)
    )
    acct["out-of-range coordinates (Assam bbox)"] = int((~in_range).sum())
    out = out[in_range]

    out = out[OUTPUT_COLUMNS].reset_index(drop=True)

    # ---- Verification: every block matches the shapefile ----
    g = gpd.read_file(SHP_4DSS)
    g.columns = [c.strip() for c in g.columns]
    shp_blocks = set(g["Block_name"].dropna().astype(str).str.strip().str.upper())
    out_blocks = set(out["block_name"].unique())
    unmatched_blocks = sorted(out_blocks - shp_blocks)

    # ---- Report ----
    print("\n=== ROW ACCOUNTING ===")
    print(f"  source rows                : {n0}")
    for reason, n in acct.items():
        print(f"  dropped: {reason:42s}: {n}")
    print(f"  final rows                 : {len(out)}")

    print("\n=== TOP UNMATCHED ODK BLOCKS (LEAF Block == no match) ===")
    for name, cnt in top_unmatched.items():
        print(f"  {cnt:6d}  {name}")

    print("\n=== BLOCK / DISTRICT COVERAGE ===")
    print(f"  distinct blocks    : {out['block_name'].nunique()}")
    print(f"  distinct districts : {out['district_name'].nunique()}")
    print(f"  blocks matching shapefile : {len(out_blocks & shp_blocks)}")
    if unmatched_blocks:
        print(f"  !! blocks NOT in shapefile (INVISIBLE): {len(unmatched_blocks)}")
        sub = out[out["block_name"].isin(unmatched_blocks)]
        for blk in unmatched_blocks:
            d = sub[sub["block_name"] == blk]
            print(f"     {blk:25s} ({d['district_name'].iloc[0]}) villages={len(d)}")
    else:
        print("  all blocks match the shapefile.")

    print("\n=== BLOCK-NAME FIXES APPLIED ===")
    for k, v in sorted(BLOCK_NAME_FIXES.items()):
        n = int((out["block_name"] == v).sum())
        print(f"  {k:20s} -> {v:20s} (rows now under target: {n})")

    # ---- Continuity vs the old 14 blocks ----
    if VILLAGES_CSV.exists():
        old = pd.read_csv(VILLAGES_CSV)
        old_counts = old.groupby(old["block_name"].str.upper()).size()
        # apply same fixes to old names for fair compare
        old_counts.index = [BLOCK_NAME_FIXES.get(b, b) for b in old_counts.index]
        new_counts = out.groupby("block_name").size()
        print("\n=== CONTINUITY: old 14 blocks (old spelling -> canonical) ===")
        print(f"  {'block (canonical)':25s} {'old':>6s} {'new':>6s}  note")
        for blk in sorted(old_counts.index):
            o = int(old_counts.get(blk, 0))
            nn = int(new_counts.get(blk, 0))
            note = ""
            if nn == 0:
                note = "MISSING in new"
            elif nn < o * 0.8:
                note = f"REGRESSION (-{round(100*(o-nn)/o)}%)"
            print(f"  {blk:25s} {o:6d} {nn:6d}  {note}")

    if dry_run:
        print("\n[dry-run] not writing.")
        return 0

    out.to_csv(VILLAGES_CSV, index=False, encoding="utf-8")
    print(f"\nWrote {VILLAGES_CSV} : {len(out)} rows, "
          f"{out['block_name'].nunique()} blocks, "
          f"{out['district_name'].nunique()} districts.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return build(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
