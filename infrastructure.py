"""
Infrastructure POI store: vet centres, pharmacies, input shops, etc.

Loaded from leaf_flask/data/infrastructure.csv. Schema (case-insensitive headers):
  type, name, lat, long, district_name, block_name, gp_name, vill_name

Supports CSV upload (replace) and a nearest-N-to-cluster-centroid query.
"""

import math
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

import pandas as pd

from clustering import haversine_km

DATA_DIR = Path(__file__).parent / "data"
INFRA_CSV = DATA_DIR / "infrastructure.csv"

REQUIRED_COLS = ("type", "name", "lat", "long")
OPTIONAL_COLS = ("district_name", "block_name", "gp_name", "vill_name")
ALL_COLS = REQUIRED_COLS + OPTIONAL_COLS

_lock = Lock()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=list(ALL_COLS))


def load_infrastructure() -> pd.DataFrame:
    if not INFRA_CSV.exists():
        return _empty_df()
    df = pd.read_csv(INFRA_CSV)
    df.columns = [c.strip() for c in df.columns]
    for col in OPTIONAL_COLS:
        if col not in df.columns:
            df[col] = None
    return df


def list_infrastructure(
    type_: Optional[str] = None,
    block: Optional[str] = None,
    district: Optional[str] = None,
) -> List[Dict]:
    df = load_infrastructure()
    if df.empty:
        return []
    if type_:
        df = df[df["type"].astype(str).str.lower() == type_.lower()]
    if block:
        df = df[df["block_name"] == block]
    if district:
        df = df[df["district_name"] == district]
    return df.where(df.notna(), None).to_dict(orient="records")


def import_infrastructure_csv(csv_text: str) -> int:
    """Replace the entire infrastructure dataset. Returns row count."""
    from io import StringIO
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
    with _lock:
        INFRA_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(INFRA_CSV, index=False)
    return len(df)


def nearest_to_point(
    lat: float,
    lon: float,
    type_: Optional[str] = None,
    n: int = 5,
    max_km: Optional[float] = None,
) -> List[Dict]:
    """Return up to `n` nearest POIs to (lat, lon), optionally filtered by type
    and a maximum distance. Adds a `distance_km` field to each row."""
    df = load_infrastructure()
    if df.empty:
        return []
    if type_:
        df = df[df["type"].astype(str).str.lower() == type_.lower()]
    if df.empty:
        return []
    df = df.copy()
    df["distance_km"] = df.apply(
        lambda r: haversine_km(lat, lon, float(r["lat"]), float(r["long"])), axis=1
    )
    if max_km is not None:
        df = df[df["distance_km"] <= float(max_km)]
    df = df.sort_values("distance_km").head(int(n))
    return df.where(df.notna(), None).to_dict(orient="records")
