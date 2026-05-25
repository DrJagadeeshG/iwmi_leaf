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


# Required ID columns that must never be renamed/removed on the block values
# sheet (they key every block to its data and geometry).
BLOCK_VALUES_ID_COLS = ["BLOCK_ID", "STATE_ID", "DISTRICT_I", "id", "Block_name"]
DSS_INPUT_REQUIRED_COLS = ["Cluster", "I_variable", "range_min", "range_max"]


def validate_sheets():
    """
    Guardrails for the config sheets (LEAF-60): check the structure users edit
    in Google Sheets and report problems in plain language *before* they break
    the dashboard. Read-only; never mutates data.

    Returns: { "ok": bool, "issues": [ {sheet, severity, message} ] }
    where severity is "error" (will break things) or "warning" (worth a look).
    """
    import pandas as pd
    issues = []

    def add(sheet, severity, message):
        issues.append({"sheet": sheet, "severity": severity, "message": message})

    # --- Block values sheet -------------------------------------------------
    bv = get_sheet("block_values")
    if bv is None:
        add("block_values", "error", "Block values sheet could not be loaded.")
    else:
        cols = list(bv.columns)
        missing = [c for c in BLOCK_VALUES_ID_COLS if c not in cols]
        if missing:
            add("block_values", "error",
                f"Missing required ID column(s): {', '.join(missing)}. Do not rename or delete columns A-E.")

        if "BLOCK_ID" in cols:
            dupes = bv["BLOCK_ID"].dropna()
            dupe_vals = dupes[dupes.duplicated()].unique().tolist()
            if dupe_vals:
                add("block_values", "error",
                    f"Duplicate BLOCK_ID value(s): {', '.join(map(str, dupe_vals[:10]))}"
                    + (" …" if len(dupe_vals) > 10 else "") + ". Each block must have a unique ID.")

        if "Block_name" in cols:
            blank = int(bv["Block_name"].isna().sum() + (bv["Block_name"].astype(str).str.strip() == "").sum())
            if blank:
                add("block_values", "warning", f"{blank} row(s) have an empty Block_name.")

        # Variable columns should be numeric. Only flag a column that is
        # *predominantly* numeric but has stray text cells (a likely typo) -
        # columns that are entirely text are treated as legitimate text fields.
        var_cols = [c for c in cols if c not in BLOCK_VALUES_ID_COLS]
        bad_cols = []
        for c in var_cols:
            s = bv[c]
            s = s[s.notna() & (s.astype(str).str.strip() != "")]
            if len(s) == 0:
                continue
            numeric = pd.to_numeric(s, errors="coerce")
            n_bad = int(numeric.isna().sum())
            n_good = int(numeric.notna().sum())
            if n_bad > 0 and n_good >= n_bad:
                bad_cols.append(f"{c} ({n_bad})")
        if bad_cols:
            add("block_values", "warning",
                "Stray non-numeric text in numeric column(s): " + ", ".join(bad_cols[:15])
                + (" …" if len(bad_cols) > 15 else "") + ". These cells will read as 'No data'.")

    # --- DSS input (intervention config) sheet ------------------------------
    di = get_sheet("dss_input")
    if di is None:
        add("dss_input", "error", "Intervention config sheet could not be loaded.")
    else:
        cols = list(di.columns)
        missing = [c for c in DSS_INPUT_REQUIRED_COLS if c not in cols]
        if missing:
            add("dss_input", "error", f"Missing required column(s): {', '.join(missing)}.")

        if {"Cluster", "I_variable"}.issubset(cols):
            orphan = di[di["Cluster"].notna() & di["I_variable"].isna()]
            if len(orphan):
                add("dss_input", "warning",
                    f"{len(orphan)} intervention row(s) have a Cluster but no I_variable (they will be skipped).")

        if {"range_min", "range_max"}.issubset(cols):
            lo = pd.to_numeric(di["range_min"], errors="coerce")
            hi = pd.to_numeric(di["range_max"], errors="coerce")
            bad = int((lo > hi).sum())
            if bad:
                add("dss_input", "error", f"{bad} row(s) have range_min greater than range_max.")

        # Cross-sheet: every I_variable should exist as a block_values column.
        if bv is not None and "I_variable" in cols:
            bv_cols = set(bv.columns)
            unknown = sorted({str(v).strip() for v in di["I_variable"].dropna()
                              if str(v).strip() and str(v).strip() not in bv_cols})
            if unknown:
                add("dss_input", "warning",
                    "I_variable code(s) not found in the block values sheet: "
                    + ", ".join(unknown[:15]) + (" …" if len(unknown) > 15 else "") + ".")

    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}


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
