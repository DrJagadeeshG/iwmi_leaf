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
    # LEAF-59: end-user update sheet. Exposes a handful of friendly-named
    # livestock columns so block coordinators can update those values without
    # touching the ~120-column coded sheet. URL is set when Faiz publishes the
    # sheet; until then the overlay is a no-op (block_values is used as-is).
    "user_update": "",
}


# LEAF-59: friendly column name in the end-user sheet -> coded column in
# block_values. The user sheet uses the long, human-readable names; on load we
# overlay the user's values into the matching coded column so the rest of the
# pipeline (DSS_input2 mappings, feasibility, map colours) keeps working
# untouched. Keep this map short (Faiz: "5-7 named variables") so the user sheet
# stays simple. Friendly names mirror DSS_input2's I_label column where possible.
USER_FRIENDLY_MAP = {
    "Cattle density (per 100 hectares)":  "BF",
    "Buffalo density (per 100 hectares)": "BG",
    "Sheep density (per 100 hectares)":   "BH",
    "Goat density (per 100 hectares)":    "BI",
    "Pig density (per 100 hectares)":     "BN",
    "Poultry density (per 100 hectares)": "BO",
    "Total households":                   "BX",
}

# Cache: { key: (dataframe, timestamp) }
_cache = {}
CACHE_TTL = 300  # 5 minutes


def _fetch_sheet(key):
    """Fetch a Google Sheet CSV by key. Returns DataFrame or None on failure.

    Returns None for unconfigured keys (empty URL) — used by the optional
    user_update overlay so the rest of the pipeline can continue if the
    end-user sheet hasn't been published yet (LEAF-59).
    """
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

        # Convergence cards: a variable tagged for BOTH the Biophysical and
        # Infrastructure cards (the "Cluster card" tag column) is a stale-tag
        # leftover — the drill-down can only show it on one card. Detect the tag
        # column by content (same approach as get_block_convergence) and flag any
        # I_variable carrying conflicting card tags so it can be cleaned up.
        if "I_variable" in cols:
            tag_col, best = None, 0
            for c in cols:
                if c == "group":
                    continue
                vals = di[c].astype(str).str.strip().str.lower()
                n = int(vals.isin(["biophysical", "infrastructure"]).sum())
                if n > best:
                    best, tag_col = n, c
            if tag_col is not None:
                seen = {}  # code -> set of card tags
                for _, r in di.iterrows():
                    tag = str(r.get(tag_col) or "").strip().lower()
                    if tag not in ("biophysical", "infrastructure"):
                        continue
                    code = r.get("I_variable")
                    if code is None or pd.isna(code) or not str(code).strip():
                        add("dss_input", "warning",
                            f"A row with no I_variable is tagged '{tag.title()}' in "
                            f"the '{tag_col}' column; it will be ignored.")
                        continue
                    seen.setdefault(str(code).strip(), set()).add(tag)
                both = sorted(c for c, t in seen.items() if len(t) > 1)
                if both:
                    add("dss_input", "warning",
                        "Variable(s) tagged for BOTH the Biophysical and Infrastructure "
                        "cards in the '" + tag_col + "' column: " + ", ".join(both)
                        + ". Each variable should carry only one card tag; the last "
                        "tag in the sheet currently wins.")

    # --- End-user update sheet (LEAF-59) ------------------------------------
    # Only validate if the user has actually published a sheet — silence the
    # warning when the URL is empty (the overlay is a designed no-op then).
    if SHEET_URLS.get("user_update"):
        uu = get_sheet("user_update")
        if uu is None:
            add("user_update", "warning", "End-user update sheet URL is set but the sheet could not be loaded.")
        else:
            cols = list(uu.columns)
            if "Block_name" not in cols:
                add("user_update", "error",
                    "End-user update sheet is missing the required 'Block_name' column.")
            else:
                blank = int(uu["Block_name"].isna().sum() + (uu["Block_name"].astype(str).str.strip() == "").sum())
                if blank:
                    add("user_update", "warning", f"{blank} row(s) have an empty Block_name.")
            unknown = [c for c in cols
                       if c != "Block_name" and c not in USER_FRIENDLY_MAP]
            if unknown:
                add("user_update", "warning",
                    "Column(s) not in the friendly-name map (their values will be ignored): "
                    + ", ".join(unknown[:10]) + (" …" if len(unknown) > 10 else "")
                    + ". Expected one of: " + ", ".join(USER_FRIENDLY_MAP.keys()) + ".")

    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}


def get_block_values_overlaid():
    """Return block_values with the end-user update sheet overlaid on top
    (LEAF-59).

    Loads the coded block_values sheet, then if a user_update sheet is
    configured and reachable, walks USER_FRIENDLY_MAP and copies each
    friendly column into its coded counterpart for every row that matches by
    Block_name. User values WIN over the coded sheet (the whole point — the
    end user updates here, we overlay).

    No-op when user_update is unconfigured or empty: returns the unmodified
    block_values sheet so the rest of the pipeline keeps working until Faiz
    publishes the end-user sheet.
    """
    bv = get_sheet("block_values")
    if bv is None:
        return None

    user_df = get_sheet("user_update")
    if user_df is None or len(user_df) == 0:
        return bv

    if "Block_name" not in user_df.columns or "Block_name" not in bv.columns:
        print("[google_sheets] user_update or block_values missing Block_name — overlay skipped.")
        return bv

    bv = bv.copy()
    # Index block_values by upper-cased Block_name for case-insensitive joins.
    bv_idx = {str(b).strip().upper(): i for i, b in enumerate(bv["Block_name"]) if pd.notna(b)}

    applied = 0
    for friendly, coded in USER_FRIENDLY_MAP.items():
        if friendly not in user_df.columns or coded not in bv.columns:
            continue
        for _, row in user_df.iterrows():
            block_name = str(row.get("Block_name", "")).strip().upper()
            new_value = row.get(friendly)
            if not block_name or pd.isna(new_value):
                continue
            target_i = bv_idx.get(block_name)
            if target_i is None:
                continue
            bv.at[target_i, coded] = new_value
            applied += 1
    if applied:
        print(f"[google_sheets] user_update overlay: applied {applied} value(s) across {len(USER_FRIENDLY_MAP)} friendly columns.")
    return bv


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
