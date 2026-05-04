"""
Village data loader and cluster persistence for LEAF DSS.

- Village seed data (lat/long + commodity member counts) is read from
  leaf_flask/data/villages.csv. This is the algorithm input; replaced by ODK
  feed in production.
- Cluster persistence is backed by Postgres (Supabase). Public function
  signatures are unchanged from the prior file-store implementation, so app.py
  routes do not need to change.
"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from psycopg2.extras import Json, execute_values

from clustering import (
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
    """Aggregate SHG counts for one block, shaped for the right-side panel."""
    df = load_shg_kobo()
    if df.empty:
        return {"block_name": block_name, "available": False}
    sub = df[df["block_name"].str.upper() == block_name.upper()]
    if sub.empty:
        return {"block_name": block_name, "available": False}

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


def list_blocks_with_villages() -> List[Dict]:
    df = load_villages()
    grouped = (
        df.groupby(["district_name", "block_name"])
        .size()
        .reset_index(name="village_count")
    )
    return grouped.to_dict(orient="records")


def villages_for_block(block_name: str) -> pd.DataFrame:
    df = load_villages()
    return df[df["block_name"] == block_name].copy()


def villages_geojson(block_name: Optional[str] = None) -> Dict:
    df = load_villages()
    if block_name is not None:
        df = df[df["block_name"] == block_name]
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
    "centroid_lat, centroid_lon, pashu_sakhi, block_coordinator, finalized, dashboard"
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


def get_clusters(
    block_name: Optional[str] = None,
    commodity: Optional[str] = None,
    district_name: Optional[str] = None,
) -> List[Dict]:
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
    return [_row_to_cluster(r, villages_map.get(r["cluster_id"], [])) for r in rows]


def get_cluster(cluster_id: str) -> Optional[Dict]:
    with get_cursor(commit=False) as cur:
        cur.execute(f"SELECT {CLUSTER_COLS} FROM clusters WHERE cluster_id = %s", (cluster_id,))
        row = cur.fetchone()
    if row is None:
        return None
    villages_map = _fetch_villages([cluster_id])
    return _row_to_cluster(row, villages_map.get(cluster_id, []))


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


def regenerate_clusters(
    block_name: Optional[str] = None,
    commodity: Optional[str] = None,
    params: Optional[Dict] = None,
) -> List[Dict]:
    """Run the algorithm and replace stored clusters for the given scope."""
    df = load_villages()
    blocks = [block_name] if block_name else sorted(df["block_name"].dropna().unique().tolist())
    new_clusters: List[Cluster] = []
    for b in blocks:
        if commodity:
            new_clusters.extend(cluster_block_commodity(df, b, commodity, params))
        else:
            for cs in cluster_block_all(df, b, params).values():
                new_clusters.extend(cs)

    payload = [c.to_dict() for c in new_clusters]
    with get_cursor(commit=True) as cur:
        _delete_clusters(cur, block_name=block_name, commodity=commodity)
        _insert_clusters(cur, payload)
    return payload


def replace_clusters_from_records(records: List[Dict], scope: Dict) -> int:
    """Replace stored clusters within `scope` (block_name, optional commodity) with `records`.

    Each record needs: cluster_id, commodity, block_name, district_name, villages (list of
    {vill_name, gp_name, lat, long, members}), plus optional pashu_sakhi, block_coordinator.
    Derived fields (total_members, max_span_km, centroid) are recomputed.
    """
    from clustering import _max_pairwise_km

    block_name = scope.get("block_name")
    commodity = scope.get("commodity")
    if not block_name:
        raise ValueError("scope.block_name is required")

    cleaned: List[Dict] = []
    for r in records:
        if r.get("block_name") != block_name:
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


def clusters_to_csv(clusters: List[Dict]) -> str:
    """Flatten clusters to a row-per-village CSV string for download/edit/upload."""
    rows = []
    for c in clusters:
        for v in c.get("villages", []):
            rows.append({
                "cluster_id": c.get("cluster_id"),
                "commodity": c.get("commodity"),
                "district_name": c.get("district_name"),
                "block_name": c.get("block_name"),
                "vill_name": v.get("vill_name"),
                "gp_name": v.get("gp_name"),
                "lat": v.get("lat"),
                "long": v.get("long"),
                "members": v.get("members"),
                "pashu_sakhi": c.get("pashu_sakhi"),
                "block_coordinator": c.get("block_coordinator"),
            })
    if not rows:
        return ("cluster_id,commodity,district_name,block_name,vill_name,gp_name,"
                "lat,long,members,pashu_sakhi,block_coordinator\n")
    df = pd.DataFrame(rows)
    return df.to_csv(index=False)


def csv_text_to_records(csv_text: str) -> List[Dict]:
    """Parse a clusters CSV (row-per-village) back into nested cluster records."""
    from io import StringIO
    df = pd.read_csv(StringIO(csv_text))
    df.columns = [c.strip() for c in df.columns]
    records: Dict[str, Dict] = {}
    for _, row in df.iterrows():
        cid = str(row["cluster_id"])
        rec = records.setdefault(cid, {
            "cluster_id": cid,
            "commodity": row.get("commodity"),
            "district_name": row.get("district_name"),
            "block_name": row.get("block_name"),
            "villages": [],
            "pashu_sakhi": row.get("pashu_sakhi") if pd.notna(row.get("pashu_sakhi")) else None,
            "block_coordinator": row.get("block_coordinator") if pd.notna(row.get("block_coordinator")) else None,
        })
        rec["villages"].append({
            "vill_name": row.get("vill_name"),
            "gp_name": row.get("gp_name"),
            "lat": float(row["lat"]),
            "long": float(row["long"]),
            "members": int(row["members"]) if pd.notna(row.get("members")) else 0,
        })
    return list(records.values())
