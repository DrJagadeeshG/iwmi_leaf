"""
Build data/villages.csv from the client SHG survey workbook.

Expands cluster-planning coverage to all LEAF blocks that match the block
shapefile (data/4DSS_VAR_2.0.shp Block_name), from the consolidated client
survey (`Village Location Detail` sheet).

Source format (SHG_Assam_Consolidated_final_Jun22, Jun 2026)
------------------------------------------------------------
This consolidated export differs from the earlier `*_WithLEAF.xlsx`:
  - It has NO pre-computed `LEAF Block` / `LEAF District` / `ODK Block` columns.
    Block / district come straight from the survey's own `Block` / `District`.
  - Activity columns use verbose labels ("Number of SHG members engaged in
    dairy production") instead of Title-Case ("Dairy Production").
The schema written to villages.csv is UNCHANGED (same OUTPUT_COLUMNS), so the
app, clustering, and CSV download/upload cycle keep working as-is.

Pipeline (mirrors ingest_kobo.py commodity semantics 1:1):
  - Coordinates: numeric, sanity-clamped to the Assam bounding box; rows with
    missing / out-of-range coordinates are dropped (can't be placed or clustered).
  - Block assignment (name-authoritative, polygon fallback):
      * Take the survey `Block` (UPPER), apply BLOCK_NAME_FIXES (verified spelling
        variants), and where the result matches a shapefile block name (exact or
        normalised), TRUST that name. District is taken from the canonical
        block -> district map derived from the shapefile (NOT the survey column),
        so blocks group under the SAME districts the dashboard shows.
      * Rows whose block name does NOT match the shapefile are routed to a
        point-in-polygon recovery against data/4DSS_VAR_2.0.shp: the village is
        assigned to whichever block polygon contains it (district from the
        polygon's DISTRICT_I -> Block_assam Dist_name). Rows that fall outside
        every polygon are dropped and counted. This covers the survey's new /
        renamed blocks that are absent from the 217-block shapefile (e.g.
        NAHARKATIA, GOALPARA, NALBARI) by placing their villages in the
        containing shapefile block.
  - SIDLI CHIRANG: the survey carries a single 'SIDLI-CHIRANG' block but the
    shapefile has 'SIDLI CHIRANG I' and 'II'. It is intentionally NOT in
    BLOCK_NAME_FIXES, so it lands in the polygon-recovery path and is split
    between I and II by the containing polygon (nearest-polygon fallback in a
    metric CRS for boundary points).
  - Commodities: the survey activity columns map 1:1 to the Kobo snake_case keys,
    then aggregate into the 6 clustering commodities exactly as
    ingest_kobo.COMMODITY_BUCKETS does. Feed / Fodder / Livestock transport /
    Meat shop (and the other non-clustering activities) are surfaced under the
    "other activities" columns, not the 6 commodity buckets.

Usage:
    $env:PYTHONUTF8=1
    python scripts/build_village_master.py            # write data/villages.csv
    python scripts/build_village_master.py --dry-run   # report only, no write
"""

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
# Raw client survey workbook. Lives in source_data/ (gitignored — it carries
# enumerator PII); only the derived data/villages.csv is committed.
SURVEY_XLSX = REPO / "source_data" / "SHG_Assam_Consolidated_final_Jun22.xlsx"
SURVEY_SHEET = "Village Location Detail"
VILLAGES_CSV = DATA / "villages.csv"
SHP_4DSS = DATA / "4DSS_VAR_2.0.shp"
SHP_BLOCK_ASSAM = DATA / "Block_assam.shp"  # DISTRICT_I -> Dist_name lookup

# Metric CRS for nearest-polygon distance (UTM 46N covers Assam).
METRIC_CRS = "EPSG:32646"

# Assam bounding box.
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

# Survey Block spelling (UPPER) -> shapefile-canonical Block_name (UPPER).
# Every value is verified present in data/4DSS_VAR_2.0.shp Block_name. Spelling
# variants only; no two survey blocks collide onto one shapefile block.
# SIDLI-CHIRANG is intentionally omitted: split spatially into I / II.
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
    "SOOTEA": "SOOTIA",
    "TAPATTARY": "TAPATTARI",
}

OUTPUT_COLUMNS = [
    "district_name", "block_name", "gp_name", "vill_name", "lat", "long",
    "Dairy", "Goatery", "Piggery", "Backyard_Poultry", "Duckery", "Fishery_Activity",
] + list(OTHER_BUCKETS.keys())


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


def norm_name(s):
    """Normalise a block name for fuzzy comparison: lowercase, strip everything
    that isn't a letter or digit (spaces, hyphens, punctuation, newlines)."""
    if pd.isna(s):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def load_block_polygons():
    """Block polygons with canonical UPPER Block_name and UPPER district_name.

    district_name comes from data/Block_assam.shp (DISTRICT_I -> Dist_name),
    uppercased to match the villages.csv convention.
    """
    g = gpd.read_file(SHP_4DSS)
    g.columns = [c.strip() for c in g.columns]
    g = g[["Block_name", "DISTRICT_I", "geometry"]].copy()
    g["block_name"] = g["Block_name"].astype(str).str.strip().str.upper()
    g["block_norm"] = g["block_name"].map(norm_name)

    gb = gpd.read_file(SHP_BLOCK_ASSAM)
    gb.columns = [c.strip() for c in gb.columns]
    dist_map = (
        gb.dropna(subset=["DISTRICT_I", "Dist_name"])
        .drop_duplicates("DISTRICT_I")
        .set_index("DISTRICT_I")["Dist_name"]
        .to_dict()
    )
    g["district_name"] = (
        g["DISTRICT_I"].map(dist_map).astype(str).str.strip().str.upper()
    )
    return g[["block_name", "block_norm", "district_name", "geometry"]]


def points_gdf(df, lon_col="long", lat_col="lat"):
    return gpd.GeoDataFrame(
        df.copy(),
        geometry=[Point(xy) for xy in zip(df[lon_col], df[lat_col])],
        crs="EPSG:4326",
    )


def assign_containing_block(pts, polys, cols):
    """Point-in-polygon join. Returns the input frame with `cols` from the
    containing polygon (NaN where a point is outside every polygon). De-duplicates
    points on a shared edge (keep first). Drops pre-existing columns on `pts` that
    collide with the polygon attribute names so the join keeps polygon values
    un-suffixed."""
    left = pts.drop(columns=[c for c in cols if c in pts.columns])
    j = gpd.sjoin(left, polys[cols + ["geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    return j.drop(columns=[c for c in ["index_right"] if c in j.columns])


def nearest_block(pts, polys):
    """For each point, the block_name/district_name of the nearest polygon
    (computed in a metric CRS). Used as the boundary fallback in recovery."""
    pm = pts.to_crs(METRIC_CRS)
    polym = polys.to_crs(METRIC_CRS).reset_index(drop=True)
    out_block, out_dist = [], []
    for geom in pm.geometry:
        d = polym.geometry.distance(geom)
        i = d.idxmin()
        out_block.append(polym.loc[i, "block_name"])
        out_dist.append(polym.loc[i, "district_name"])
    return out_block, out_dist


def survey_to_out(df, district_series, block_series):
    """Build the output frame (names + numeric coords + 6 commodities + other
    activities) from a survey sub-frame. district_name / block_name come from the
    passed series so the same builder serves name-matched rows and polygon-
    recovered rows. Commodity aggregation is identical to ingest_kobo."""
    out = pd.DataFrame({
        "district_name": district_series.map(upper_strip),
        "block_name": block_series.map(upper_strip),
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
    return out


def canonical_block_district():
    """Authoritative block_name(UPPER) -> district_name(UPPER), derived exactly
    as the main app does: 4DSS_VAR_2.0 Block_name -> DISTRICT_I -> Block_assam
    Dist_name. Used to set the district for name-matched rows so blocks group
    under the SAME districts the dashboard shows."""
    g = gpd.read_file(SHP_4DSS)
    g.columns = [c.strip() for c in g.columns]
    gb = gpd.read_file(SHP_BLOCK_ASSAM)
    gb.columns = [c.strip() for c in gb.columns]
    dist_map = dict(zip(gb["DISTRICT_I"], gb["Dist_name"]))
    out = {}
    for _, r in g.iterrows():
        bn = str(r.get("Block_name", "")).strip().upper()
        d = dist_map.get(r.get("DISTRICT_I"))
        if bn and d is not None and str(d).strip():
            out[bn] = str(d).strip().upper()
    return out


def build(dry_run: bool = False) -> int:
    print(f"Reading {SURVEY_XLSX} :: {SURVEY_SHEET}")
    df = pd.read_excel(SURVEY_XLSX, sheet_name=SURVEY_SHEET)
    n0 = len(df)
    print(f"Source rows: {n0}")

    # Verify expected activity columns exist (verbose schema).
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

    acct = {}

    # 1. Coordinate sanity (drop missing + out-of-Assam-range up front).
    df = df.copy()
    df["_lat"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["_long"] = pd.to_numeric(df["Longitude"], errors="coerce")
    coord_na = df["_lat"].isna() | df["_long"].isna()
    acct["missing numeric lat/long"] = int(coord_na.sum())
    df = df[~coord_na]
    in_range = df["_lat"].between(LAT_MIN, LAT_MAX) & df["_long"].between(LON_MIN, LON_MAX)
    acct["out-of-range coordinates (Assam bbox)"] = int((~in_range).sum())
    df = df[in_range].copy()

    # 2. Block name -> UPPER, apply spelling fixes.
    df["_block"] = df["Block"].map(upper_strip).replace(BLOCK_NAME_FIXES)

    # 3. Split: name-matched (block in shapefile, exact or normalised) vs no-match.
    polys = load_block_polygons()
    shp_blocks = set(polys["block_name"].unique())
    shp_norm = {norm_name(b): b for b in shp_blocks}

    def to_canonical(b):
        if b in shp_blocks:
            return b
        nb = shp_norm.get(norm_name(b))
        return nb  # None if no normalised match

    df["_canon_block"] = df["_block"].map(to_canonical)
    matched_mask = df["_canon_block"].notna()
    acct["name-matched to shapefile block"] = int(matched_mask.sum())
    acct["no name match (routed to polygon recovery)"] = int((~matched_mask).sum())

    canon = canonical_block_district()
    # Blocks that genuinely span >1 district in the shapefile: polygon district
    # is authoritative for the recovery path; for the name-matched path we use the
    # canonical map (single district per block name there by construction).
    multi_district_blocks = set(
        polys.groupby("block_name")["district_name"].nunique().pipe(
            lambda s: s[s > 1].index
        )
    )

    # ---- 3a. Name-matched rows: trust block name, district from canonical map. ----
    mt = df[matched_mask].copy()
    out_matched = survey_to_out(mt, mt["_canon_block"].map(canon).fillna(mt["District"]), mt["_canon_block"])
    out_matched = out_matched[OUTPUT_COLUMNS].reset_index(drop=True)

    # ---- 3b. No-match rows: point-in-polygon recovery. ----
    nm = df[~matched_mask].copy()
    rec_acct = {"no-match total": int(len(nm))}
    out_recovered = pd.DataFrame(columns=OUTPUT_COLUMNS)
    nm_block_report = None
    if len(nm):
        nm["lat"] = nm["_lat"]
        nm["long"] = nm["_long"]
        nm_pts = points_gdf(nm)
        nm_j = assign_containing_block(
            nm_pts, polys, ["block_name", "district_name"]
        )
        in_poly = nm_j["block_name"].notna()
        rec_acct["recovered (inside a block polygon)"] = int(in_poly.sum())
        rec_acct["dropped (outside all polygons)"] = int((~in_poly).sum())
        keep_idx = nm_j.index[in_poly]
        nm_in = nm.loc[keep_idx]
        rec_block = nm_j.loc[keep_idx, "block_name"]
        rec_dist = nm_j.loc[keep_idx, "district_name"]
        out_recovered = survey_to_out(nm_in, rec_dist, rec_block)
        out_recovered = out_recovered[OUTPUT_COLUMNS].reset_index(drop=True)
        nm_block_report = (
            df.loc[~matched_mask, "_block"].value_counts()
        )

    out = pd.concat([out_matched, out_recovered], ignore_index=True)

    # ---- Verification: every block matches the shapefile ----
    out_blocks = set(out["block_name"].unique())
    unmatched_blocks = sorted(out_blocks - shp_blocks)

    # ---- Report ----
    print("\n=== ROW ACCOUNTING ===")
    print(f"  source rows                : {n0}")
    for reason, n in acct.items():
        print(f"  {reason:46s}: {n}")
    print(f"  final rows                 : {len(out)}")

    print("\n=== POLYGON RECOVERY (no-match blocks) ===")
    for reason, n in rec_acct.items():
        print(f"  {reason:46s}: {n}")
    if nm_block_report is not None:
        print("\n  -- survey blocks routed to recovery (top 30) --")
        for blk, cnt in nm_block_report.head(30).items():
            print(f"     {blk:30s} {cnt}")

    print("\n=== BLOCK / DISTRICT COVERAGE ===")
    print(f"  distinct blocks    : {out['block_name'].nunique()}")
    print(f"  distinct districts : {out['district_name'].nunique()}")
    print(f"  blocks matching shapefile : {len(out_blocks & shp_blocks)} / {len(shp_blocks)}")
    if unmatched_blocks:
        print(f"  !! blocks NOT in shapefile (INVISIBLE): {len(unmatched_blocks)}")
        for blk in unmatched_blocks:
            d = out[out["block_name"] == blk]
            print(f"     {blk:25s} ({d['district_name'].iloc[0]}) villages={len(d)}")
    else:
        print("  all blocks match the shapefile.")

    # ---- Continuity vs the previous villages.csv ----
    if VILLAGES_CSV.exists():
        old = pd.read_csv(VILLAGES_CSV)
        old_counts = old.groupby(old["block_name"].str.upper()).size()
        new_counts = out.groupby("block_name").size()
        regressions = []
        for blk in sorted(old_counts.index):
            o = int(old_counts.get(blk, 0))
            nn = int(new_counts.get(blk, 0))
            if nn == 0:
                regressions.append((blk, o, nn, "MISSING in new"))
            elif nn < o * 0.8:
                regressions.append((blk, o, nn, f"REGRESSION (-{round(100*(o-nn)/o)}%)"))
        print("\n=== CONTINUITY vs previous villages.csv ===")
        print(f"  previous rows: {len(old)}  blocks: {old['block_name'].str.upper().nunique()}")
        print(f"  new rows     : {len(out)}  blocks: {out['block_name'].nunique()}")
        if regressions:
            print(f"  !! {len(regressions)} block(s) lost >=20% of villages:")
            for blk, o, nn, note in regressions[:40]:
                print(f"     {blk:25s} {o:6d} -> {nn:6d}  {note}")
        else:
            print("  no block lost >=20% of its villages.")

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
