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

Spatial recovery step (added on feat/village-master-21k)
--------------------------------------------------------
The client's matching step left 5,367 rows as LEAF Block '— no match'. Some of
those are real LEAF blocks the name-matcher missed. We recover a conservative,
defensible subset by a point-in-polygon join of (Longitude, Latitude) against
the block polygons in data/4DSS_VAR_2.0.shp, with the district name taken from
the polygon (DISTRICT_I -> Dist_name via data/Block_assam.shp), NOT from the
survey columns. Recovery rules:

  1. Both-signals rule (general, conservative): a '— no match' row is recovered
     ONLY when its point falls inside a block polygon AND the row's own ODK block
     name ('Final ODK Block' / 'ODK Block (Standardised)' / 'Block') fuzzy-matches
     that polygon's Block_name (case-insensitive, ignoring spaces/hyphens/
     punctuation). The ~5,000 other unmatched rows are deliberately left out.
     This rule recovers LAHOWAL (the block exists in the shapefile and the ODK
     name matches the containing polygon).

  2. NAHORKOTEYA exception (known case): 'NAHARKATIA'/'NAHORKOTEYA' is ABSENT from
     the 219-block shapefile, so the name-match in rule 1 cannot fire. These rows
     are recovered purely by their containing polygon (assigned to whichever block
     they fall inside). The receiving-block distribution is reported. Rows that
     fall outside every polygon are dropped and counted.

  3. SIDLI CHIRANG split: the survey carries a single 'SIDLI-CHIRANG' block but
     the shapefile has 'SIDLI CHIRANG I' and 'II'. The already-included rows are
     re-assigned between I and II by their containing polygon, with a nearest-
     polygon fallback (computed in a metric CRS) for points on the shared
     boundary or just outside both. No blanket map to I anymore.

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
SURVEY_XLSX = Path(r"C:\Users\sindh\Downloads\SHG_Assam_June2_WithLEAF.xlsx")
SURVEY_SHEET = "Village Location Detail"
VILLAGES_CSV = DATA / "villages.csv"
SHP_4DSS = DATA / "4DSS_VAR_2.0.shp"
SHP_BLOCK_ASSAM = DATA / "Block_assam.shp"  # DISTRICT_I -> Dist_name lookup

# Metric CRS for nearest-polygon distance (UTM 46N covers Assam).
METRIC_CRS = "EPSG:32646"

# ODK block-name source columns checked for the both-signals name match.
ODK_NAME_COLS = ["Final ODK Block", "ODK Block (Standardised)", "Block"]

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

# "Other" livelihood activities outside the 6 clustering commodities. These were
# previously dropped (so the planner's "other activities" panel was empty for
# village-master blocks); now aggregated per village so block_shg_summary can
# surface them. Output column names match villages._OTHER_KEYS labels exactly.
OTHER_BUCKETS = {
    "Fodder cultivation": ["Fodder Cultivation Or Production"],
    "Feed manufacturing": ["Feed Manufacturing Or Production Unit"],
    "Livestock transport": ["Livestock Transportation"],
    "Meat shop": ["Meat Shop"],
}

# Survey LEAF Block spelling (UPPER) -> shapefile-canonical Block_name (UPPER).
# Every value is verified present in data/4DSS_VAR_2.0.shp Block_name. These are
# spelling variants only; no two survey blocks collide onto one shapefile block.
# NOTE: SIDLI-CHIRANG is split into "SIDLI CHIRANG I"/"II" in the shapefile; the
# survey carries a single block, so it is NOT mapped here — it is split between
# the two polygons spatially in the recovery step (see split_sidli_chirang).
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
    # SIDLI-CHIRANG intentionally omitted: split spatially into I / II.
    "SOOTEA": "SOOTIA",
    "TAPATTARY": "TAPATTARI",
}

OUTPUT_COLUMNS = [
    "district_name", "block_name", "gp_name", "vill_name", "lat", "long",
    "Dairy", "Goatery", "Piggery", "Backyard_Poultry", "Duckery", "Fishery_Activity",
    "Fodder cultivation", "Feed manufacturing", "Livestock transport", "Meat shop",
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
    points that land on a shared edge (keep first). Drops any pre-existing columns
    on `pts` that collide with the polygon attribute names so the join keeps the
    polygon values un-suffixed."""
    left = pts.drop(columns=[c for c in cols if c in pts.columns])
    j = gpd.sjoin(left, polys[cols + ["geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    return j.drop(columns=[c for c in ["index_right"] if c in j.columns])


def survey_to_out(df, district_series, block_series):
    """Build the output frame (names + numeric coords + 6 commodities) from a
    survey sub-frame. district_name / block_name come from the passed series so
    the same builder serves matched rows (LEAF cols) and recovered rows (polygon
    cols). Commodity aggregation is identical to ingest_kobo (1:1 survey->kobo
    key, then bucket)."""
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
    # "Other" activities (Fodder/Feed/Transport/Meat) - aggregated like commodities.
    for label, survey_cols in OTHER_BUCKETS.items():
        out[label] = pd.concat(
            [df[c].map(to_int) for c in survey_cols], axis=1
        ).sum(axis=1).astype(int)
    return out


def nearest_block(pts, polys):
    """For each point, the Block_name/district_name of the nearest polygon
    (computed in a metric CRS). Used as the SIDLI-CHIRANG boundary fallback."""
    pm = pts.to_crs(METRIC_CRS)
    polym = polys.to_crs(METRIC_CRS).reset_index(drop=True)
    out_block, out_dist = [], []
    for geom in pm.geometry:
        d = polym.geometry.distance(geom)
        i = d.idxmin()
        out_block.append(polym.loc[i, "block_name"])
        out_dist.append(polym.loc[i, "district_name"])
    return out_block, out_dist


def canonical_block_district():
    """Authoritative block_name(UPPER) -> district_name(UPPER), derived exactly
    as the main app does (data_utils.load_shapefile / load_district_mapping):
    4DSS_VAR_2.0 Block_name -> DISTRICT_I -> Block_assam Dist_name. Used to
    override the survey's district labels so the village master groups blocks
    under the SAME districts the dashboard shows (the survey carried old names
    - Nowgaon/Sibsagar/Kamrup Rural/Karimganj/N.C.Hills - and old parent
    districts for the 8 new carved districts)."""
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

    acct = {}

    # 1. Drop junk row.
    junk = df["Location Status"].astype(str) == "Column5"
    acct["junk (Location Status=='Column5')"] = int(junk.sum())
    df = df[~junk]

    # 2. Split off LEAF Block '— no match' (and any NaN LEAF Block). These are
    #    NOT discarded outright: they are routed through the spatial recovery step.
    lb = df["LEAF Block"]
    nomatch = lb.isna() | (lb.astype(str).str.strip() == NO_MATCH)
    nm_view = df[nomatch].copy()
    acct["LEAF Block '— no match' / blank (routed to recovery)"] = int(nomatch.sum())
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

    # 4. Build output frame for the matched rows.
    out = survey_to_out(df, df["LEAF District"], df["LEAF Block"])

    # 4a. Apply block-name spelling fixes -> shapefile-canonical.
    out["block_name"] = out["block_name"].replace(BLOCK_NAME_FIXES)

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

    # ================================================================
    # SPATIAL RECOVERY (see module docstring for the rules)
    # ================================================================
    polys = load_block_polygons()
    # Blocks that genuinely span >1 district in the shapefile (e.g. LAKHIPUR,
    # BINNAKANDI): for these the polygon's own district is authoritative and must
    # NOT be overwritten by the matched-set label during reconciliation.
    multi_district_blocks = set(
        polys.groupby("block_name")["district_name"].nunique().pipe(
            lambda s: s[s > 1].index
        )
    )

    # ---- 3a. SIDLI CHIRANG: split already-included rows between I and II. ----
    sidli_mask = out["block_name"] == "SIDLI-CHIRANG"
    sidli_report = {}
    if sidli_mask.any():
        sc = out[sidli_mask].copy()
        sc_polys = polys[polys["block_name"].str.startswith("SIDLI CHIRANG")]
        sc_pts = points_gdf(sc)
        sc_j = assign_containing_block(
            sc_pts, sc_polys, ["block_name", "district_name"]
        )
        inside = sc_j["block_name"].notna()
        # nearest-polygon fallback for points on the boundary / just outside both
        if (~inside).any():
            nb, nd = nearest_block(sc_pts[~inside.values], sc_polys)
            sc_j.loc[~inside, "block_name"] = nb
            sc_j.loc[~inside, "district_name"] = nd
        out.loc[sidli_mask, "block_name"] = sc_j["block_name"].values
        out.loc[sidli_mask, "district_name"] = sc_j["district_name"].values
        sidli_report = {
            "I": int((sc_j["block_name"] == "SIDLI CHIRANG I").sum()),
            "II": int((sc_j["block_name"] == "SIDLI CHIRANG II").sum()),
            "fallback_nearest": int((~inside).sum()),
        }

    # ---- 3b. Recover '— no match' rows by point-in-polygon. ----
    nm = nm_view.copy()
    nm["lat"] = pd.to_numeric(nm["Latitude"], errors="coerce")
    nm["long"] = pd.to_numeric(nm["Longitude"], errors="coerce")
    nm_coord_ok = (
        nm["lat"].notna() & nm["long"].notna()
        & nm["lat"].between(LAT_MIN, LAT_MAX)
        & nm["long"].between(LON_MIN, LON_MAX)
    )
    rec_acct = {
        "no-match total": int(len(nm)),
        "no-match dropped (no/out-of-range coords)": int((~nm_coord_ok).sum()),
    }
    nm = nm[nm_coord_ok]

    nm_pts = points_gdf(nm)
    nm_j = assign_containing_block(
        nm_pts, polys, ["block_name", "district_name", "block_norm"]
    )
    in_poly = nm_j["block_name"].notna()
    rec_acct["no-match outside all polygons (dropped)"] = int((~in_poly).sum())
    nm_in = nm_j[in_poly].copy()

    # ODK-name fuzzy match against the containing polygon's block name.
    odk_norm = pd.DataFrame(
        {c: nm.loc[nm_in.index, c].map(norm_name) for c in ODK_NAME_COLS}
    )
    name_match = (
        odk_norm.eq(nm_in["block_norm"], axis=0).any(axis=1)
    )

    # NAHORKOTEYA: block absent from shapefile, so name_match can't fire — recover
    # by polygon alone. Identify these rows via their ODK name.
    odk_known = pd.Series(False, index=nm_in.index)
    for c in ODK_NAME_COLS:
        odk_known = odk_known | nm.loc[nm_in.index, c].map(norm_name).str.contains(
            "nahorkoteya|naharkatia|nahorkatia", na=False
        )

    recover = name_match | odk_known
    rec_acct["recovered: both-signals (name + polygon)"] = int(name_match.sum())
    rec_acct["recovered: NAHORKOTEYA (polygon only)"] = int(
        (odk_known & ~name_match).sum()
    )
    rec_acct["not recovered (no name match, not a known case)"] = int(
        (~recover).sum()
    )

    nm_rec = nm.loc[nm_in.index][recover.values].copy()
    rec_block = nm_in.loc[recover, "block_name"]
    rec_dist = nm_in.loc[recover, "district_name"]

    rec_out = survey_to_out(nm_rec, rec_dist, rec_block)
    rec_out = rec_out[OUTPUT_COLUMNS].reset_index(drop=True)

    # District-label reconciliation: when a recovered row's block ALREADY exists
    # in the matched set under a SINGLE district label, adopt that label so the
    # block never appears under two district names in the UI. (The survey's LEAF
    # District labels use a few older district names that differ from the
    # shapefile's, e.g. NOWGAON vs NAGAON; this keeps recovered rows consistent
    # with the dominant existing labelling instead of introducing a 2nd district.)
    matched_dist = (
        out.groupby("block_name")["district_name"].agg(
            lambda s: s.iloc[0] if s.nunique() == 1 else None
        )
    )

    def reconcile(r):
        # Genuinely multi-district blocks keep the authoritative polygon district.
        if r["block_name"] in multi_district_blocks:
            return r["district_name"]
        return matched_dist.get(r["block_name"]) or r["district_name"]

    rec_out["district_name"] = rec_out.apply(reconcile, axis=1)

    # NAHORKOTEYA receiving-block distribution (report).
    nahor_idx = nm_in.index[(odk_known & ~name_match).values]
    nahor_dist = (
        nm_in.loc[nahor_idx, "block_name"].value_counts() if len(nahor_idx) else None
    )
    # NAHORKOTEYA rows that fell OUTSIDE every polygon (dropped above):
    nahor_all = pd.Series(False, index=nm.index)
    for c in ODK_NAME_COLS:
        nahor_all = nahor_all | nm[c].map(norm_name).str.contains(
            "nahorkoteya|naharkatia|nahorkatia", na=False
        )
    in_poly_full = in_poly.reindex(nm.index).fillna(False)
    nahor_outside = int((nahor_all & ~in_poly_full).sum())

    # Both-signals receiving-block distribution (report).
    bonus_dist = nm_in.loc[name_match[name_match].index, "block_name"].value_counts()

    # ---- Merge recovered rows into the master frame. ----
    out = pd.concat([out, rec_out], ignore_index=True)

    # ---- District alignment: override survey district labels with the
    # canonical block->district map so /clustering groups blocks under the SAME
    # districts as the main dashboard (5 renames + 8 new carved districts). All
    # village blocks already match a shapefile block name (BLOCK_NAME_FIXES), so
    # every row resolves; any that don't keep their survey district + are flagged.
    canon = canonical_block_district()
    mapped = out["block_name"].str.upper().map(canon)
    unresolved = sorted(out.loc[mapped.isna(), "block_name"].unique().tolist())
    if unresolved:
        print(f"\n[district-align] {len(unresolved)} block(s) NOT in shapefile map "
              f"(kept survey district): {unresolved[:15]}")
    out["district_name"] = mapped.fillna(out["district_name"])

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

    print("\n=== SPATIAL RECOVERY ===")
    for reason, n in rec_acct.items():
        print(f"  {reason:52s}: {n}")

    print("\n  -- LAHOWAL (recovered via both-signals rule) --")
    lah = int((rec_out["block_name"] == "LAHOWAL").sum())
    print(f"     LAHOWAL recovered rows: {lah}")

    print("\n  -- NAHORKOTEYA (recovered by polygon only; block absent from shp) --")
    if nahor_dist is not None:
        for blk, cnt in nahor_dist.items():
            print(f"     {blk:25s} {cnt}")
        print(f"     {'OUTSIDE all polygons (dropped)':25s} {nahor_outside}")
    else:
        print("     (none found)")

    print("\n  -- SIDLI CHIRANG split (already-included rows) --")
    if sidli_report:
        print(f"     SIDLI CHIRANG I : {sidli_report['I']}")
        print(f"     SIDLI CHIRANG II: {sidli_report['II']}")
        print(f"     (nearest-poly fallback used for {sidli_report['fallback_nearest']} boundary rows)")
    else:
        print("     (no SIDLI-CHIRANG rows in matched set)")

    print("\n  -- BONUS both-signals recoveries by block --")
    for blk, cnt in bonus_dist.items():
        print(f"     {blk:25s} {cnt}")

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
