"""
Google Sheets Integration
Fetches DSS metadata from a published Google Sheet with TTL caching.
Falls back to local CSV if the sheet is unreachable.
"""

import time
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Published Google Sheet CSV URLs
SHEET_URLS = {
    "dss_input": "https://docs.google.com/spreadsheets/d/e/2PACX-1vS225C6-L0oWTuG1qqJfBrwcBE0yWSn9pH6VjybzgBZNXTb2S38k7KMJv-ZDkDY_hSW_a1IUnV5aKfw/pub?output=csv",
    "block_values": "https://docs.google.com/spreadsheets/d/e/2PACX-1vSc0gk_Rbsi1n7Z9EY1qA532_lF_xe7y5GGPRxuyUXgawBdZVrF4RveIGiaMU9itNlmK7oLmuCffGlk/pub?output=csv",
}

# Cache: { key: (dataframe, timestamp) }
_cache = {}
CACHE_TTL = 300  # 5 minutes


def _fetch_sheet(key):
    """Fetch a Google Sheet CSV by key. Returns DataFrame or None on failure."""
    url = SHEET_URLS.get(key)
    if not url:
        return None
    try:
        df = pd.read_csv(url, encoding='utf-8-sig')
        df.columns = [col.strip() for col in df.columns]
        return df
    except Exception as e:
        print(f"[google_sheets] Failed to fetch '{key}' from Google Sheets: {e}")
        return None


def _load_local_csv(key):
    """Fallback: load from local CSV file."""
    local_files = {
        "dss_input": DATA_DIR / "DSS_input2.csv",
        "block_values": DATA_DIR / "block_values.csv",
    }
    path = local_files.get(key)
    if path and path.exists():
        df = pd.read_csv(path, encoding='utf-8-sig')
        df.columns = [col.strip() for col in df.columns]
        return df
    return None


def get_sheet(key):
    """
    Get a DataFrame for the given sheet key.
    Uses TTL cache, fetches from Google Sheets, falls back to local CSV.
    """
    now = time.time()
    cached = _cache.get(key)

    if cached:
        df, ts = cached
        if now - ts < CACHE_TTL:
            return df

    # Try Google Sheets
    df = _fetch_sheet(key)
    if df is not None:
        _cache[key] = (df, now)
        return df

    # If we have stale cache, use it
    if cached:
        print(f"[google_sheets] Using stale cache for '{key}'")
        return cached[0]

    # Fallback to local CSV
    print(f"[google_sheets] Falling back to local CSV for '{key}'")
    df = _load_local_csv(key)
    if df is not None:
        _cache[key] = (df, now)
    return df


def refresh(key=None):
    """
    Force-refresh one or all sheets. Returns dict of {key: success_bool}.
    """
    keys = [key] if key else list(SHEET_URLS.keys())
    results = {}
    for k in keys:
        df = _fetch_sheet(k)
        if df is not None:
            _cache[k] = (df, time.time())
            results[k] = True
        else:
            results[k] = False
    return results


def get_status():
    """Return cache status for all sheets."""
    now = time.time()
    status = {}
    for key in SHEET_URLS:
        cached = _cache.get(key)
        if cached:
            df, ts = cached
            age = now - ts
            status[key] = {
                "cached": True,
                "rows": len(df),
                "columns": len(df.columns),
                "age_seconds": round(age),
                "stale": age >= CACHE_TTL,
                "source_url": SHEET_URLS[key],
            }
        else:
            status[key] = {
                "cached": False,
                "source_url": SHEET_URLS[key],
            }
    return status
