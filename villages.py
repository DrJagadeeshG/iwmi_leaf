"""
Village data loader and cluster persistence for LEAF DSS.

- Village seed data (lat/long + commodity member counts) is read from
  leaf_flask/data/villages.csv. This is the algorithm input; replaced by ODK
  feed in production.
- Cluster persistence is backed by Postgres (Supabase). Public function
  signatures are unchanged from the prior file-store implementation, so app.py
  routes do not need to change.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from psycopg2.extras import Json, execute_values

from clustering import (
    ALGO_VERSION,
    Cluster,
    COMMODITIES,
    DEFAULT_PARAMS,
    cluster_block_all,
    cluster_block_commodity,
)
from db import get_cursor

DATA_DIR = Path(__file__).parent / "data"
VILLAGES_CSV = DATA_DIR / "villages.csv"
SHG_CSV = DATA_DIR / "shg_kobo_clean.csv"

# Mapping from raw Kobo activity column to the 6 clustering commodities.
# Activities not listed below are surfaced under "other" in the SHG summary.
_COMMODITY_MAP = {
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
_OTHER_KEYS = {
    "fodder_cultivation": "Fodder cultivation",
    "feed_manufacturing": "Feed manufacturing",
    "livestock_transport": "Livestock transport",
    "meat_shop": "Meat shop",
}


@lru_cache(maxsize=1)
def load_villages() -> pd.DataFrame:
    """Load all villages with lat/long and commodity member counts."""
    if not VILLAGES_CSV.exists():
        raise FileNotFoundError(f"Village data not found at {VILLAGES_CSV}")
    df = pd.read_csv(VILLAGES_CSV)
    df.columns = [c.strip() for c in df.columns]
    return df


@lru_cache(maxsize=1)
def load_shg_kobo() -> pd.DataFrame:
    """Load the raw SHG dataset (one row per village, 25 activity columns).

    Used by the block summary panel; falls back to an empty frame when the
    sidecar CSV hasn't been ingested yet so non-Kobo blocks still work.
    """
    if not SHG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(SHG_CSV)
    df.columns = [c.strip() for c in df.columns]
    return df


def block_shg_summary(block_name: str) -> Dict:
    """Aggregate SHG counts for one block, shaped for the right-side panel.

    Prefers the raw Kobo sidecar dump (richer: per-activity breakdown); blocks
    only present in the June-2 village master (most of the 173) fall back to
    aggregating villages.csv so the panel shows real numbers instead of
    "No SHG form data" (Faiz, Boginodi report 07-Jun)."""
    df = load_shg_kobo()
    if df.empty:
        return _village_master_summary(block_name)
    sub = df[df["block_name"].str.upper() == block_name.upper()]
    if sub.empty:
        return _village_master_summary(block_name)

    has_gps = sub["lat"].notna() & sub["long"].notna()
    activities_raw = {
        k: int(sub[k].fillna(0).sum())
        for keys in _COMMODITY_MAP.values() for k in keys
    }
    activities_raw.update({k: int(sub[k].fillna(0).sum()) for k in _OTHER_KEYS})

    commodities = {
        commodity: sum(activities_raw.get(k, 0) for k in keys)
        for commodity, keys in _COMMODITY_MAP.items()
    }
    other = {label: activities_raw.get(key, 0) for key, label in _OTHER_KEYS.items()}

    return {
        "district_name": str(sub["district_name"].iloc[0]),
        "block_name": str(sub["block_name"].iloc[0]),
        "available": True,
        "villages_total": int(len(sub)),
        "villages_with_gps": int(has_gps.sum()),
        "villages_without_gps": int((~has_gps).sum()),
        "gp_count": int(sub["gp_name"].nunique()),
        "gps": sorted(sub["gp_name"].dropna().unique().tolist()),
        "members_total": int(sum(commodities.values()) + sum(other.values())),
        "commodities": commodities,
        "other": other,
        "activities_raw": activities_raw,
    }


def _village_master_summary(block_name: str) -> Dict:
    """SHG summary built from villages.csv for blocks absent from the Kobo
    sidecar. Same shape as the Kobo path; commodity totals are the master's
    aggregated counts, so there is no per-activity "other" breakdown."""
    df = load_villages()
    sub = df[df["block_name"].astype(str).str.upper() == str(block_name).upper()]
    if sub.empty:
        return {"block_name": block_name, "available": False}

    has_gps = sub["lat"].notna() & sub["long"].notna()
    commodities = {
        c: int(pd.to_numeric(sub[c], errors="coerce").fillna(0).sum())
        for c in _COMMODITY_MAP if c in sub.columns
    }

    return {
        "district_name": str(sub["district_name"].iloc[0]),
        "block_name": str(sub["block_name"].iloc[0]),
        "available": True,
        "source": "village_master",
        "villages_total": int(len(sub)),
        "villages_with_gps": int(has_gps.sum()),
        "villages_without_gps": int((~has_gps).sum()),
        "gp_count": int(sub["gp_name"].nunique()),
        "gps": sorted(sub["gp_name"].dropna().unique().tolist()),
        "members_total": int(sum(commodities.values())),
        "commodities": commodities,
        "other": {},
        "activities_raw": {},
    }


def list_blocks_with_villages() -> List[Dict]:
    df = load_villages()
    grouped = (
        df.groupby(["district_name", "block_name"])
        .size()
        .reset_index(name="village_count")
    )
    return grouped.to_dict(orient="records")


def _canonical_block(block_name: Optional[str]) -> Optional[str]:
    """Resolve any-case block input to the exact casing used in the village
    master, so cluster DB lookups / stores key consistently. The frontend sends
    MMUA display case (e.g. "Bhergaon") while the master is upper ("BHERGAON");
    without this, case-sensitive cluster queries silently return nothing.
    Returns the input unchanged if the block isn't in the master."""
    if not block_name:
        return block_name
    df = load_villages()
    hit = df[df["block_name"].astype(str).str.upper() == str(block_name).upper()]
    return str(hit["block_name"].iloc[0]) if not hit.empty else block_name


def villages_for_block(block_name: str) -> pd.DataFrame:
    df = load_villages()
    # Case-insensitive: Kobo data lands as ALL-CAPS but dropdown values can
    # arrive in /api/locations display case after the cluster-planner's
    # name reconciliation step.
    return df[df["block_name"].str.upper().str.strip() == block_name.upper().strip()].copy()


def villages_geojson(block_name: Optional[str] = None) -> Dict:
    df = load_villages()
    if block_name is not None:
        df = df[df["block_name"].str.upper().str.strip() == block_name.upper().strip()]
    features = []
    for _, row in df.iterrows():
        props = {k: (None if pd.isna(row[k]) else row[k]) for k in df.columns if k not in ("lat", "long")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(row["long"]), float(row["lat"])]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def aggregate_villages(level: str, district: Optional[str] = None) -> List[Dict]:
    df = load_villages()
    if level not in ("district", "block"):
        raise ValueError("level must be 'district' or 'block'")
    if district:
        df = df[df["district_name"] == district]
    group_cols = ["district_name"] if level == "district" else ["district_name", "block_name"]
    agg = (
        df.groupby(group_cols)
        .agg(
            village_count=("vill_name", "count"),
            **{c: (c, "sum") for c in COMMODITIES if c in df.columns},
        )
        .reset_index()
    )
    return agg.to_dict(orient="records")


# =============================================================================
# Cluster store (Postgres-backed)
# =============================================================================

CLUSTER_COLS = (
    "cluster_id, commodity, block_name, district_name, total_members, max_span_km, "
    "centroid_lat, centroid_lon, pashu_sakhi, block_coordinator, finalized, locked, "
    "provisional, dashboard"
)


def _row_to_cluster(row: Dict, villages: List[Dict]) -> Dict:
    return {
        "cluster_id": row["cluster_id"],
        "commodity": row["commodity"],
        "block_name": row["block_name"],
        "district_name": row["district_name"],
        "total_members": int(row["total_members"]) if row["total_members"] is not None else 0,
        "max_span_km": float(row["max_span_km"]) if row["max_span_km"] is not None else 0.0,
        "centroid_lat": float(row["centroid_lat"]) if row["centroid_lat"] is not None else 0.0,
        "centroid_lon": float(row["centroid_lon"]) if row["centroid_lon"] is not None else 0.0,
        "pashu_sakhi": row["pashu_sakhi"],
        "block_coordinator": row["block_coordinator"],
        "finalized": bool(row["finalized"]),
        "locked": bool(row.get("locked", False)),
        "provisional": bool(row.get("provisional", False)),
        "dashboard": row["dashboard"],
        "villages": villages,
        "village_indices": [v["village_index"] for v in villages if v.get("village_index") is not None],
    }


def _fetch_villages(cluster_ids: List[str]) -> Dict[str, List[Dict]]:
    if not cluster_ids:
        return {}
    with get_cursor(commit=False) as cur:
        cur.execute(
            'SELECT cluster_id, vill_name, gp_name, lat, "long", members, village_index, position '
            'FROM cluster_villages WHERE cluster_id = ANY(%s) ORDER BY cluster_id, position',
            (cluster_ids,),
        )
        out: Dict[str, List[Dict]] = {cid: [] for cid in cluster_ids}
        for r in cur.fetchall():
            out[r["cluster_id"]].append({
                "vill_name": r["vill_name"],
                "gp_name": r["gp_name"],
                "lat": float(r["lat"]) if r["lat"] is not None else None,
                "long": float(r["long"]) if r["long"] is not None else None,
                "members": int(r["members"]) if r["members"] is not None else 0,
                "village_index": r["village_index"],
            })
        return out


def _cluster_code(c: Dict) -> str:
    """Human-readable unique cluster code (Faiz 2026-06-07): hyphen-separated -
    first two letters of district + block + commodity (intervention type), then
    the within-tier sequence number - e.g. MO-BH-GO-01 (MOrigaon / BHurbandha /
    GOatery / fundable #1) and MO-BH-GO-P01 for the provisional tier. Derived at
    read time from cluster_num, so CSV splits/merges renumber cleanly on the next
    read; cluster_id stays the stable internal key."""
    def two(s: Optional[str]) -> str:
        letters = "".join(ch for ch in str(s or "") if ch.isalpha())
        return (letters[:2] or "XX").upper()
    tier = "P" if c.get("provisional") else ""
    num = int(c.get("cluster_num") or 0)
    return (
        f"{two(c.get('district_name'))}-{two(c.get('block_name'))}-"
        f"{two(c.get('commodity'))}-{tier}{num:02d}"
    )


def get_clusters(
    block_name: Optional[str] = None,
    commodity: Optional[str] = None,
    district_name: Optional[str] = None,
) -> List[Dict]:
    block_name = _canonical_block(block_name)
    where, params = [], []
    if block_name:
        where.append("block_name = %s")
        params.append(block_name)
    if commodity:
        where.append("commodity = %s")
        params.append(commodity)
    if district_name:
        where.append("district_name = %s")
        params.append(district_name)
    sql = f"SELECT {CLUSTER_COLS} FROM clusters"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY block_name, commodity, cluster_id"

    with get_cursor(commit=False) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    villages_map = _fetch_villages([r["cluster_id"] for r in rows])
    clusters = [_row_to_cluster(r, villages_map.get(r["cluster_id"], [])) for r in rows]
    # Sequential numbering per (block, commodity) for the left-panel display
    # and the CSV. Fundable and provisional groups are numbered in SEPARATE
    # sequences so a below-floor "review" group never reads like a peer of a
    # fundable cluster (Faiz 2026-05-26: "Cluster 1 inside Cluster 11"). Fundable
    # -> "1", "2", ...; provisional -> "P1", "P2", .... cluster_label carries the
    # display string; cluster_num stays the within-tier integer. Restarts each
    # (block, commodity); rows are already ordered by (block, commodity,
    # cluster_id). Display-only - not persisted.
    n_fund, n_prov, last_key = 0, 0, None
    for c in clusters:
        key = (c.get("block_name"), c.get("commodity"))
        if key != last_key:
            n_fund, n_prov, last_key = 0, 0, key
        if c.get("provisional"):
            n_prov += 1
            c["cluster_num"], c["cluster_label"] = n_prov, f"P{n_prov}"
        else:
            n_fund += 1
            c["cluster_num"], c["cluster_label"] = n_fund, str(n_fund)
        c["cluster_code"] = _cluster_code(c)
    return clusters


def get_cluster(cluster_id: str) -> Optional[Dict]:
    with get_cursor(commit=False) as cur:
        cur.execute(f"SELECT {CLUSTER_COLS} FROM clusters WHERE cluster_id = %s", (cluster_id,))
        row = cur.fetchone()
    if row is None:
        return None
    villages_map = _fetch_villages([cluster_id])
    c = _row_to_cluster(row, villages_map.get(cluster_id, []))
    # Derive cluster_num/label by counting earlier clusters in the SAME tier
    # (provisional vs fundable) so single-cluster lookups match the separate-tier
    # numbering used in the list/CSV (see get_clusters).
    prov = bool(c.get("provisional"))
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM clusters "
            "WHERE block_name = %s AND commodity = %s AND provisional = %s "
            "AND cluster_id < %s",
            (c.get("block_name"), c.get("commodity"), prov, cluster_id),
        )
        n = int(cur.fetchone()["n"]) + 1
    c["cluster_num"], c["cluster_label"] = n, (f"P{n}" if prov else str(n))
    c["cluster_code"] = _cluster_code(c)
    return c


def _delete_clusters(cur, block_name: Optional[str] = None, commodity: Optional[str] = None) -> None:
    """Delete clusters in scope. cluster_villages cascades."""
    if block_name and commodity:
        cur.execute("DELETE FROM clusters WHERE block_name = %s AND commodity = %s", (block_name, commodity))
    elif block_name:
        cur.execute("DELETE FROM clusters WHERE block_name = %s", (block_name,))
    else:
        cur.execute("DELETE FROM clusters")


def _insert_clusters(cur, clusters: List[Dict]) -> None:
    if not clusters:
        return
    cluster_rows = [
        (
            c["cluster_id"], c["commodity"], c["block_name"], c.get("district_name"),
            c.get("total_members", 0), c.get("max_span_km", 0.0),
            c.get("centroid_lat", 0.0), c.get("centroid_lon", 0.0),
            c.get("pashu_sakhi"), c.get("block_coordinator"),
            bool(c.get("finalized", False)),
            bool(c.get("locked", False)),
            bool(c.get("provisional", False)),
            Json(c["dashboard"]) if c.get("dashboard") is not None else None,
        )
        for c in clusters
    ]
    execute_values(
        cur,
        f"INSERT INTO clusters ({CLUSTER_COLS}) VALUES %s",
        cluster_rows,
    )

    village_rows = []
    for c in clusters:
        for pos, v in enumerate(c.get("villages", [])):
            village_rows.append((
                c["cluster_id"],
                v.get("vill_name"),
                v.get("gp_name"),
                v.get("lat"),
                v.get("long"),
                int(v.get("members", 0)),
                v.get("village_index"),
                pos,
            ))
    if village_rows:
        execute_values(
            cur,
            'INSERT INTO cluster_villages '
            '(cluster_id, vill_name, gp_name, lat, "long", members, village_index, position) VALUES %s',
            village_rows,
        )


# =============================================================================
# Smart auto-refresh: regenerate a scope on read only when it is STALE
# (fingerprint changed) and NOT locked/finalized (no human edits to protect).
# =============================================================================

def _effective_params(params: Optional[Dict]) -> Dict:
    p = dict(DEFAULT_PARAMS)
    if params:
        for k, v in params.items():
            if k in p and v is not None:
                p[k] = v
    return p


def scope_fingerprint(block_name: str, commodity: str, params: Optional[Dict] = None) -> str:
    """Stable hash of everything that should force a regeneration: the algorithm
    version, the effective params, and the village data (name/lat/long/members)
    for this (block, commodity). Identical inputs -> identical fingerprint."""
    df = villages_for_block(block_name)
    if commodity in df.columns:
        sub = df[df[commodity] >= 1][["vill_name", "lat", "long", commodity]].copy()
        data_blob = sub.sort_values("vill_name").to_csv(index=False)
    else:
        data_blob = ""
    eff = _effective_params(params)
    # `rebalance` is OFF by default and a no-op when False, so merely adding it to
    # DEFAULT_PARAMS must NOT invalidate every existing fingerprint and trigger a
    # needless regen of all unlocked scopes. Only a TRUE rebalance changes output,
    # so it only belongs in the fingerprint then. (Drop it when False -> the hash
    # stays byte-identical to the pre-rebalance fingerprint.)
    if not eff.get("rebalance"):
        eff.pop("rebalance", None)
    payload = json.dumps(
        {"algo": ALGO_VERSION, "params": eff, "data": data_blob},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_generation_fp(block_name: str, commodity: str) -> Optional[str]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT fingerprint FROM cluster_generation WHERE block_name = %s AND commodity = %s",
            (block_name, commodity),
        )
        row = cur.fetchone()
    return row["fingerprint"] if row else None


def _set_generation_fp(cur, block_name: str, commodity: str, fingerprint: str) -> None:
    cur.execute(
        "INSERT INTO cluster_generation (block_name, commodity, fingerprint, generated_at) "
        "VALUES (%s, %s, %s, now()) "
        "ON CONFLICT (block_name, commodity) "
        "DO UPDATE SET fingerprint = EXCLUDED.fingerprint, generated_at = now()",
        (block_name, commodity, fingerprint),
    )


def scope_is_locked(block_name: str, commodity: str) -> bool:
    """True if any cluster in scope is finalized or locked (human-owned). Such
    scopes are never auto-regenerated so edits / uploaded CSVs survive reloads."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT 1 FROM clusters WHERE block_name = %s AND commodity = %s "
            "AND (finalized OR locked) LIMIT 1",
            (block_name, commodity),
        )
        return cur.fetchone() is not None


def get_or_regenerate(
    block_name: str,
    commodity: Optional[str] = None,
    district_name: Optional[str] = None,
    params: Optional[Dict] = None,
) -> List[Dict]:
    """Serve stored clusters, auto-regenerating each in-scope (block, commodity)
    only when it is stale and unlocked. Always returns the current stored set."""
    block_name = _canonical_block(block_name)
    commodities = [commodity] if commodity else list(COMMODITIES)
    for com in commodities:
        if scope_is_locked(block_name, com):
            continue  # protect human edits - never auto-regen
        if _get_generation_fp(block_name, com) == scope_fingerprint(block_name, com, params):
            continue  # fresh; also short-circuits known-empty scopes
        regenerate_clusters(block_name=block_name, commodity=com, params=params)
    return get_clusters(block_name=block_name, commodity=commodity, district_name=district_name)


def regenerate_clusters(
    block_name: Optional[str] = None,
    commodity: Optional[str] = None,
    params: Optional[Dict] = None,
) -> List[Dict]:
    """Run the algorithm and replace stored clusters for the given scope.
    Records a generation fingerprint per (block, commodity) so smart-refresh
    can tell later whether the scope is still current."""
    block_name = _canonical_block(block_name)
    df = load_villages()
    blocks = [block_name] if block_name else sorted(df["block_name"].dropna().unique().tolist())
    new_clusters: List[Cluster] = []
    scopes: List[tuple] = []  # (block, commodity) pairs actually regenerated
    for b in blocks:
        if commodity:
            new_clusters.extend(cluster_block_commodity(df, b, commodity, params))
            scopes.append((b, commodity))
        else:
            for com, cs in cluster_block_all(df, b, params).items():
                new_clusters.extend(cs)
                scopes.append((b, com))

    payload = [c.to_dict() for c in new_clusters]
    with get_cursor(commit=True) as cur:
        _delete_clusters(cur, block_name=block_name, commodity=commodity)
        _insert_clusters(cur, payload)
        for b, com in scopes:
            _set_generation_fp(cur, b, com, scope_fingerprint(b, com, params))
    return payload


def replace_clusters_from_records(records: List[Dict], scope: Dict) -> int:
    """Replace stored clusters within `scope` (block_name, optional commodity) with `records`.

    Each record needs: cluster_id, commodity, block_name, district_name, villages (list of
    {vill_name, gp_name, lat, long, members}), plus optional pashu_sakhi, block_coordinator.
    Derived fields (total_members, max_span_km, centroid) are recomputed.
    """
    from clustering import _max_pairwise_km

    block_name = _canonical_block(scope.get("block_name"))
    commodity = scope.get("commodity")
    if not block_name:
        raise ValueError("scope.block_name is required")

    cleaned: List[Dict] = []
    for r in records:
        if str(r.get("block_name") or "").upper() != str(block_name).upper():
            continue
        if commodity and r.get("commodity") != commodity:
            continue
        villages = r.get("villages") or []
        coords = [(float(v["lat"]), float(v["long"])) for v in villages]
        total = sum(int(v.get("members", 0)) for v in villages)
        c_lat = sum(c[0] for c in coords) / len(coords) if coords else 0.0
        c_lon = sum(c[1] for c in coords) / len(coords) if coords else 0.0
        cid = r.get("cluster_id") or f"{block_name}-{r.get('commodity','X')}-manual"
        cleaned.append({
            "cluster_id": cid,
            "commodity": r.get("commodity"),
            "block_name": block_name,
            "district_name": r.get("district_name"),
            "villages": villages,
            "total_members": total,
            "max_span_km": round(_max_pairwise_km(coords), 3),
            "centroid_lat": round(c_lat, 6),
            "centroid_lon": round(c_lon, 6),
            "pashu_sakhi": r.get("pashu_sakhi"),
            "block_coordinator": r.get("block_coordinator"),
            "finalized": False,
            # Human-owned: an uploaded CSV must survive smart-refresh reloads.
            "locked": True,
        })

    with get_cursor(commit=True) as cur:
        _delete_clusters(cur, block_name=block_name, commodity=commodity)
        _insert_clusters(cur, cleaned)
    return len(cleaned)


def set_cluster_finalized(cluster_id: str, finalized: bool) -> Optional[Dict]:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE clusters SET finalized = %s, updated_at = now() WHERE cluster_id = %s",
            (bool(finalized), cluster_id),
        )
        if cur.rowcount == 0:
            return None
    return get_cluster(cluster_id)


def set_cluster_dashboard(cluster_id: str, payload: Dict) -> Optional[Dict]:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE clusters SET dashboard = %s, updated_at = now() WHERE cluster_id = %s",
            (Json(payload), cluster_id),
        )
        if cur.rowcount == 0:
            return None
    return get_cluster(cluster_id)


_CSV_COLUMNS = [
    "cluster_code", "cluster_num", "cluster_id", "commodity", "district_name", "block_name",
    "gp_name", "vill_name", "lat", "long", "members", "pashu_sakhi", "block_coordinator",
]


def clusters_to_csv(clusters: List[Dict]) -> str:
    """Flatten clusters to a row-per-village CSV string for download/edit/upload.

    Schema (LEAF-44, 2026-05-29): lat/long are emitted so a user can add a
    brand-new village inline by appending a row with its coordinates. When
    a user-added vill_name doesn't exist in the village master, the parser
    uses the CSV's lat/long instead of failing the upload.
    """
    rows = []
    for c in clusters:
        for v in c.get("villages", []):
            rows.append({
                # Human-readable unique code (e.g. MOBHGO01); ignored on import
                # (cluster_id is the join key) so field edits can't corrupt it.
                "cluster_code": c.get("cluster_code"),
                # Prefer the separate-tier display label ("1" / "P1") so
                # provisional rows are unambiguous; fall back to the raw number
                # for callers that haven't been through get_clusters numbering.
                "cluster_num": c.get("cluster_label", c.get("cluster_num")),
                "cluster_id": c.get("cluster_id"),
                "commodity": c.get("commodity"),
                "district_name": c.get("district_name"),
                "block_name": c.get("block_name"),
                "gp_name": v.get("gp_name"),
                "vill_name": v.get("vill_name"),
                "lat": v.get("lat"),
                "long": v.get("long"),
                "members": v.get("members"),
                "pashu_sakhi": c.get("pashu_sakhi"),
                "block_coordinator": c.get("block_coordinator"),
            })
    if not rows:
        return ",".join(_CSV_COLUMNS) + "\n"
    df = pd.DataFrame(rows, columns=_CSV_COLUMNS)
    return df.to_csv(index=False)


def _village_coord_lookup(block_name: Optional[str]) -> Dict[str, Dict[str, float]]:
    """Build {vill_name_upper: {lat, long, gp_name}} from the village master,
    scoped to a block when given. Used by csv_text_to_records to backfill
    lat/long when the uploaded CSV omits them (current schema)."""
    try:
        df = load_villages()
    except FileNotFoundError:
        return {}
    if block_name and "block_name" in df.columns:
        df = df[df["block_name"].astype(str).str.upper() == str(block_name).upper()]
    out: Dict[str, Dict[str, float]] = {}
    for _, r in df.iterrows():
        name = r.get("vill_name")
        if not isinstance(name, str) or not name.strip():
            continue
        try:
            lat = float(r.get("lat"))
            lon = float(r.get("long"))
        except (TypeError, ValueError):
            continue
        out[name.strip().upper()] = {
            "lat": lat, "long": lon, "gp_name": r.get("gp_name"),
        }
    return out


def csv_text_to_records(csv_text: str) -> List[Dict]:
    """Parse a clusters CSV (row-per-village) back into nested cluster records.

    Accepts the current schema (lat/long included, LEAF-44) and the legacy
    schema (no lat/long). When a row provides lat/long, those values win and
    a vill_name unknown to the master is accepted as a newly-surveyed village.
    When a row omits lat/long, the parser looks them up from the master by
    (block_name, vill_name); an unknown name then fails fast with a message
    pointing at the row.
    """
    from io import StringIO
    df = pd.read_csv(StringIO(csv_text))
    df.columns = [c.strip() for c in df.columns]

    has_coords = "lat" in df.columns and "long" in df.columns
    # Build lookup once per block referenced in the CSV; small N (one block
    # per upload in practice), so keyed by block name is fine.
    coord_cache: Dict[str, Dict[str, Dict[str, float]]] = {}

    records: Dict[str, Dict] = {}
    missing: List[str] = []
    for _, row in df.iterrows():
        cid = str(row["cluster_id"])
        block = row.get("block_name")
        vill = row.get("vill_name")
        rec = records.setdefault(cid, {
            "cluster_id": cid,
            "commodity": row.get("commodity"),
            "district_name": row.get("district_name"),
            "block_name": block,
            "villages": [],
            "pashu_sakhi": row.get("pashu_sakhi") if pd.notna(row.get("pashu_sakhi")) else None,
            "block_coordinator": row.get("block_coordinator") if pd.notna(row.get("block_coordinator")) else None,
        })

        lat = lon = None
        if has_coords and pd.notna(row.get("lat")) and pd.notna(row.get("long")):
            lat = float(row["lat"])
            lon = float(row["long"])
        else:
            key = str(block) if pd.notna(block) else ""
            if key not in coord_cache:
                coord_cache[key] = _village_coord_lookup(key or None)
            hit = coord_cache[key].get(str(vill).strip().upper()) if isinstance(vill, str) else None
            if hit:
                lat, lon = hit["lat"], hit["long"]
            else:
                missing.append(f"{block} / {vill}")

        rec["villages"].append({
            "vill_name": vill,
            "gp_name": row.get("gp_name"),
            "lat": lat,
            "long": lon,
            "members": int(row["members"]) if pd.notna(row.get("members")) else 0,
        })

    if missing:
        sample = ", ".join(missing[:5])
        extra = "" if len(missing) <= 5 else f" (and {len(missing) - 5} more)"
        raise ValueError(
            f"Could not resolve lat/long for {len(missing)} village(s): {sample}{extra}. "
            "Either include lat/long columns in the CSV or use vill_name values that match the village master."
        )
    return list(records.values())
