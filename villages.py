"""
Village data loader and cluster persistence for LEAF DSS.

- Loads village-level pilot data (lat/long + commodity member counts) from
  leaf_flask/data/villages.csv (seed: MMUA Random_pointshapefile sheet).
- Maintains an in-memory cluster store keyed by cluster_id, persisted to
  leaf_flask/data/clusters.json so backend CSV upload edits survive restarts.
"""

import json
from pathlib import Path
from functools import lru_cache
from threading import Lock
from typing import Dict, List, Optional

import pandas as pd

from clustering import (
    Cluster,
    COMMODITIES,
    DEFAULT_PARAMS,
    cluster_block_all,
    cluster_block_commodity,
)

DATA_DIR = Path(__file__).parent / "data"
VILLAGES_CSV = DATA_DIR / "villages.csv"
CLUSTERS_JSON = DATA_DIR / "clusters.json"

_store_lock = Lock()


@lru_cache(maxsize=1)
def load_villages() -> pd.DataFrame:
    """Load all villages with lat/long and commodity member counts."""
    if not VILLAGES_CSV.exists():
        raise FileNotFoundError(f"Village data not found at {VILLAGES_CSV}")
    df = pd.read_csv(VILLAGES_CSV)
    df.columns = [c.strip() for c in df.columns]
    return df


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
    """Aggregate village member counts by district or block.

    `level` is one of:
      - "district": one row per district (use for state-scale map)
      - "block":    one row per (district, block) (use for district-scale map);
                    pass `district` to scope to one.
    """
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


# ---- Cluster store ----

def _load_store() -> Dict[str, Dict]:
    if not CLUSTERS_JSON.exists():
        return {}
    try:
        with open(CLUSTERS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_store(store: Dict[str, Dict]) -> None:
    CLUSTERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(CLUSTERS_JSON, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def get_clusters(
    block_name: Optional[str] = None,
    commodity: Optional[str] = None,
    district_name: Optional[str] = None,
) -> List[Dict]:
    with _store_lock:
        store = _load_store()
    out = list(store.values())
    if block_name:
        out = [c for c in out if c.get("block_name") == block_name]
    if commodity:
        out = [c for c in out if c.get("commodity") == commodity]
    if district_name:
        out = [c for c in out if c.get("district_name") == district_name]
    return out


def get_cluster(cluster_id: str) -> Optional[Dict]:
    with _store_lock:
        store = _load_store()
    return store.get(cluster_id)


def regenerate_clusters(
    block_name: Optional[str] = None,
    commodity: Optional[str] = None,
    params: Optional[Dict] = None,
) -> List[Dict]:
    """Run the algorithm and replace stored clusters for the given scope.

    Scope precedence: (block_name, commodity) > (block_name) > all blocks/all commodities.
    """
    df = load_villages()
    blocks = [block_name] if block_name else sorted(df["block_name"].dropna().unique().tolist())
    new_clusters: List[Cluster] = []
    for b in blocks:
        if commodity:
            new_clusters.extend(cluster_block_commodity(df, b, commodity, params))
        else:
            for cs in cluster_block_all(df, b, params).values():
                new_clusters.extend(cs)

    with _store_lock:
        store = _load_store()
        if block_name and commodity:
            keep = {k: v for k, v in store.items()
                    if not (v.get("block_name") == block_name and v.get("commodity") == commodity)}
        elif block_name:
            keep = {k: v for k, v in store.items() if v.get("block_name") != block_name}
        else:
            keep = {}
        for c in new_clusters:
            d = c.to_dict()
            keep[d["cluster_id"]] = d
        _save_store(keep)
    return [c.to_dict() for c in new_clusters]


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

    cleaned: Dict[str, Dict] = {}
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
        cleaned[cid] = {
            "cluster_id": cid,
            "commodity": r.get("commodity"),
            "block_name": block_name,
            "district_name": r.get("district_name"),
            "village_indices": r.get("village_indices", []),
            "villages": villages,
            "total_members": total,
            "max_span_km": round(_max_pairwise_km(coords), 3),
            "centroid_lat": round(c_lat, 6),
            "centroid_lon": round(c_lon, 6),
            "pashu_sakhi": r.get("pashu_sakhi"),
            "block_coordinator": r.get("block_coordinator"),
        }

    with _store_lock:
        store = _load_store()
        if commodity:
            keep = {k: v for k, v in store.items()
                    if not (v.get("block_name") == block_name and v.get("commodity") == commodity)}
        else:
            keep = {k: v for k, v in store.items() if v.get("block_name") != block_name}
        keep.update(cleaned)
        _save_store(keep)
    return len(cleaned)


def set_cluster_finalized(cluster_id: str, finalized: bool) -> Optional[Dict]:
    """Flip the `finalized` flag on a stored cluster. Returns updated record or None."""
    with _store_lock:
        store = _load_store()
        rec = store.get(cluster_id)
        if rec is None:
            return None
        rec["finalized"] = bool(finalized)
        store[cluster_id] = rec
        _save_store(store)
        return rec


def set_cluster_dashboard(cluster_id: str, payload: Dict) -> Optional[Dict]:
    """Attach an arbitrary dashboard JSON blob (from the external production tool)
    to a cluster. Stored under `dashboard`. Returns updated record or None."""
    with _store_lock:
        store = _load_store()
        rec = store.get(cluster_id)
        if rec is None:
            return None
        rec["dashboard"] = payload
        store[cluster_id] = rec
        _save_store(store)
        return rec


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
