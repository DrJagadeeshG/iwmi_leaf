"""
Infrastructure POI store: vet centres, pharmacies, input shops, etc.

Backed by Postgres (table `infrastructure`). CSV upload replaces the entire
dataset; nearest-N queries compute haversine in-memory after a scoped fetch.
Public function signatures are unchanged from the prior file-store version.
"""

from io import StringIO
from typing import Dict, List, Optional

import pandas as pd
from psycopg2.extras import execute_values

from clustering import haversine_km
from db import get_cursor

REQUIRED_COLS = ("type", "name", "lat", "long")
OPTIONAL_COLS = ("district_name", "block_name", "gp_name", "vill_name")
ALL_COLS = REQUIRED_COLS + OPTIONAL_COLS


def _row_to_dict(row: Dict, with_distance: Optional[float] = None) -> Dict:
    out = {
        "type": row["type"],
        "name": row["name"],
        "lat": float(row["lat"]),
        "long": float(row["long"]),
        "district_name": row.get("district_name"),
        "block_name": row.get("block_name"),
        "gp_name": row.get("gp_name"),
        "vill_name": row.get("vill_name"),
    }
    if with_distance is not None:
        out["distance_km"] = with_distance
    return out


def list_infrastructure(
    type_: Optional[str] = None,
    block: Optional[str] = None,
    district: Optional[str] = None,
) -> List[Dict]:
    where, params = [], []
    if type_:
        where.append("LOWER(type) = LOWER(%s)")
        params.append(type_)
    if block:
        where.append("block_name = %s")
        params.append(block)
    if district:
        where.append("district_name = %s")
        params.append(district)
    sql = (
        'SELECT type, name, lat, "long", district_name, block_name, gp_name, vill_name '
        'FROM infrastructure'
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY type, name"
    with get_cursor(commit=False) as cur:
        cur.execute(sql, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


def import_infrastructure_csv(csv_text: str) -> int:
    """Replace the entire infrastructure dataset. Returns row count."""
    df = pd.read_csv(StringIO(csv_text))
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Required: {list(REQUIRED_COLS)}")
    for col in OPTIONAL_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[list(ALL_COLS)]
    df["lat"] = df["lat"].astype(float)
    df["long"] = df["long"].astype(float)

    rows = [
        (
            r["type"], r["name"], r["lat"], r["long"],
            r["district_name"] if pd.notna(r["district_name"]) else None,
            r["block_name"] if pd.notna(r["block_name"]) else None,
            r["gp_name"] if pd.notna(r["gp_name"]) else None,
            r["vill_name"] if pd.notna(r["vill_name"]) else None,
        )
        for _, r in df.iterrows()
    ]

    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM infrastructure")
        if rows:
            execute_values(
                cur,
                'INSERT INTO infrastructure '
                '(type, name, lat, "long", district_name, block_name, gp_name, vill_name) VALUES %s',
                rows,
            )
    return len(rows)


def nearest_to_point(
    lat: float,
    lon: float,
    type_: Optional[str] = None,
    n: int = 5,
    max_km: Optional[float] = None,
) -> List[Dict]:
    """Return up to `n` nearest POIs to (lat, lon). Distance computed in Python
    after a type-filtered fetch. Acceptable for current dataset size; for very
    large POI sets, switch to PostGIS or earthdistance."""
    rows = list_infrastructure(type_=type_)
    if not rows:
        return []
    for r in rows:
        r["distance_km"] = haversine_km(lat, lon, r["lat"], r["long"])
    if max_km is not None:
        rows = [r for r in rows if r["distance_km"] <= float(max_km)]
    rows.sort(key=lambda r: r["distance_km"])
    return rows[: int(n)]
