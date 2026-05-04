"""
One-off Kobo ingestion: append a block's village-level SHG data into
villages.csv (clustering input, 6 commodity sums) and shg_kobo_clean.csv
(panel input, 25 raw activity counts).

Re-runnable: removes existing rows for the (district, block) before append.

Usage:
    python ingest_kobo.py --xlsx <path> --district DIBRUGARH --block NAHARKATIA
    # Rename to match shapefile canonical name (Kobo's "PUB-CHAIDUAR"
    # -> shapefile's "PUB CHAIDUAR"):
    python ingest_kobo.py --xlsx <p> --district BISWANATH --block PUB-CHAIDUAR \
        --canonical-block "PUB CHAIDUAR"
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
VILLAGES_CSV = DATA_DIR / "villages.csv"
SHG_CSV = DATA_DIR / "shg_kobo_clean.csv"

# Kobo column indices (0-based) for the labelled "all versions" export.
COL_LAT, COL_LON = 1, 2
COL_DISTRICT = 5
COL_BLOCK_SEL, COL_BLOCK_TXT = 6, 7
COL_GP_SEL, COL_GP_TXT = 8, 9
COL_VIL_SEL, COL_VIL_TXT = 10, 11
COL_SUBMITTED = 42

# Map of activity column index -> short snake_case key.
ACTIVITY_COLS = {
    13: "dairy_production",
    14: "goat_farming",
    15: "goat_breeding_farm",
    16: "goat_kid_nursery",
    36: "goat_nursery",
    17: "pig_farming",
    18: "pig_breeding_farm",
    19: "pig_piglet_nursery",
    37: "pig_nursery",
    20: "poultry_backyard",
    21: "poultry_broiler",
    38: "poultry_hen",
    23: "poultry_duck_hatchery",
    22: "duck_rearing",
    28: "fishery_activity",
    29: "fishery_hatchery",
    30: "fishery_equip_trading",
    31: "fishery_equip_lending",
    32: "fishery_equip_mfg",
    33: "fish_trading",
    39: "fishery_nursery_pond",
    24: "feed_manufacturing",
    25: "fodder_cultivation",
    26: "livestock_transport",
    27: "meat_shop",
}

# Aggregation into the 6 clustering commodities.
COMMODITY_BUCKETS = {
    "Dairy": ["dairy_production"],
    "Goatery": ["goat_farming", "goat_breeding_farm", "goat_kid_nursery", "goat_nursery"],
    "Piggery": ["pig_farming", "pig_breeding_farm", "pig_piglet_nursery", "pig_nursery"],
    "Backyard_Poultry": ["poultry_backyard", "poultry_broiler", "poultry_hen", "poultry_duck_hatchery"],
    "Duckery": ["duck_rearing"],
    "Fishery_Activity": [
        "fishery_activity", "fishery_hatchery", "fishery_equip_trading",
        "fishery_equip_lending", "fishery_equip_mfg", "fish_trading",
        "fishery_nursery_pond",
    ],
}


def to_int(v):
    try:
        if v is None or pd.isna(v):
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def load_block_rows(xlsx_path: Path, district: str, block: str) -> pd.DataFrame:
    """Return one row per Kobo submission for the target block (no dedupe yet)."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active

    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        d = (row[COL_DISTRICT] or "").__str__().strip().upper()
        b = (row[COL_BLOCK_SEL] or row[COL_BLOCK_TXT] or "").__str__().strip().upper()
        if d != district.upper() or b != block.upper():
            continue
        rec = {
            "district_name": d,
            "block_name": b,
            "gp_name": (row[COL_GP_SEL] or row[COL_GP_TXT] or "").__str__().strip().upper(),
            "vill_name": (row[COL_VIL_SEL] or row[COL_VIL_TXT] or "").__str__().strip().upper(),
            "lat": row[COL_LAT],
            "long": row[COL_LON],
            "_submitted": row[COL_SUBMITTED],
        }
        for idx, key in ACTIVITY_COLS.items():
            rec[key] = to_int(row[idx])
        out.append(rec)
    return pd.DataFrame(out)


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (gp_name, vill_name). Keep the latest submission, then sum
    activity counts across any duplicates that have lat/long defined."""
    if df.empty:
        return df
    df = df[df["vill_name"].astype(bool)]
    df = df.sort_values("_submitted").drop_duplicates(
        subset=["gp_name", "vill_name"], keep="last"
    )
    return df.drop(columns=["_submitted"])


def make_villages_rows(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        rec = {
            "district_name": r["district_name"],
            "block_name": r["block_name"],
            "gp_name": r["gp_name"],
            "vill_name": r["vill_name"],
            "lat": r["lat"],
            "long": r["long"],
        }
        for commodity, keys in COMMODITY_BUCKETS.items():
            rec[commodity] = sum(int(r[k]) for k in keys)
        rows.append(rec)
    return pd.DataFrame(rows)


def make_shg_rows(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["district_name", "block_name", "gp_name", "vill_name", "lat", "long"] + list(ACTIVITY_COLS.values())
    return df[cols].copy()


def replace_block_rows(target_csv: Path, new_rows: pd.DataFrame, district: str, block: str) -> None:
    if target_csv.exists():
        existing = pd.read_csv(target_csv)
        keep = ~(
            (existing["district_name"].str.upper() == district.upper())
            & (existing["block_name"].str.upper() == block.upper())
        )
        merged = pd.concat([existing[keep], new_rows], ignore_index=True)
    else:
        merged = new_rows
    merged.to_csv(target_csv, index=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx", required=True, type=Path)
    p.add_argument("--district", required=True)
    p.add_argument("--block", required=True,
                   help="Block name as it appears in the Kobo form")
    p.add_argument("--canonical-block",
                   help="Optional: store under this name instead (e.g. when the "
                        "Kobo label has spelling/punctuation drift from the "
                        "shapefile canonical name).")
    p.add_argument("--canonical-district",
                   help="Optional: store under this district name instead.")
    args = p.parse_args()

    raw = load_block_rows(args.xlsx, args.district, args.block)
    if raw.empty:
        print(f"No rows found for {args.district} / {args.block}", file=sys.stderr)
        return 2

    cleaned = dedupe(raw)
    with_gps = cleaned[cleaned["lat"].notna() & cleaned["long"].notna()].copy()
    no_gps = len(cleaned) - len(with_gps)

    out_block = (args.canonical_block or args.block).upper()
    out_district = (args.canonical_district or args.district).upper()
    cleaned["block_name"] = out_block
    cleaned["district_name"] = out_district
    with_gps["block_name"] = out_block
    with_gps["district_name"] = out_district

    villages_rows = make_villages_rows(with_gps)
    shg_rows = make_shg_rows(cleaned)

    replace_block_rows(VILLAGES_CSV, villages_rows, out_district, out_block)
    replace_block_rows(SHG_CSV, shg_rows, out_district, out_block)

    rename_note = "" if out_block == args.block.upper() else f" (renamed from {args.block})"
    print(f"{out_district}/{out_block}{rename_note}: {len(cleaned)} unique villages "
          f"({len(with_gps)} with GPS, {no_gps} without)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
