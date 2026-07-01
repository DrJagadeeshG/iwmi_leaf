"""
Data Loading Utilities
Handles shapefile and metadata loading with caching
"""

import geopandas as gpd
import pandas as pd
import json
from pathlib import Path
from functools import lru_cache

# Data directory - inside leaf_flask/data/
DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def load_district_boundaries():
    """Load pre-computed district boundary GeoJSON."""
    geojson_path = DATA_DIR / "districts.geojson"
    if not geojson_path.exists():
        return None
    with open(geojson_path) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_protected_areas():
    """Load Protected Areas of India shapefile and return as GeoJSON dict."""
    shapefile_path = DATA_DIR / "protected_areas" / "Protected_Area_India_Final.shp"

    if not shapefile_path.exists():
        return None

    gdf = gpd.read_file(shapefile_path)

    # Ensure CRS is WGS84
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    # Keep only useful columns
    keep_cols = ['name', 'Type', 'State', 'Area', 'Year', 'geometry']
    gdf = gdf[[c for c in keep_cols if c in gdf.columns]]

    # Simplify geometry for performance
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.005, preserve_topology=True)

    return json.loads(gdf.to_json())


@lru_cache(maxsize=1)
def load_district_mapping():
    """Load district ID to name mapping from Block_assam shapefile."""
    block_assam_path = DATA_DIR / "Block_assam.shp"

    if not block_assam_path.exists():
        return {}

    block_assam = gpd.read_file(block_assam_path)
    return dict(zip(block_assam['DISTRICT_I'], block_assam['Dist_name']))


@lru_cache(maxsize=1)
def _load_shapefile_geometry():
    """Load block geometries from shapefile (cached permanently)."""
    shapefile_path = DATA_DIR / "4DSS_VAR_2.0.shp"

    if not shapefile_path.exists():
        raise FileNotFoundError(f"Shapefile not found at {shapefile_path}")

    gdf = gpd.read_file(shapefile_path)

    # Ensure CRS is WGS84 (EPSG:4326) for web mapping
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    # Normalize column names (strip whitespace)
    gdf.columns = [col.strip() for col in gdf.columns]

    # Simplify geometries for better performance
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.001, preserve_topology=True)

    # Keep only ID columns + geometry
    id_cols = ['BLOCK_ID', 'STATE_ID', 'DISTRICT_I', 'id', 'Block_name', 'geometry']
    return gdf[[c for c in id_cols if c in gdf.columns]]


# ---------------------------------------------------------------------------
# District label overrides
# ---------------------------------------------------------------------------
# Kamrup Metropolitan was carved out of Kamrup, but Block_assam.shp still codes
# BOTH districts as DISTRICT_I 266 "Kamrup". Because the district name is derived
# purely from DISTRICT_I, the three Kamrup-Metro CD blocks otherwise render under
# "Kamrup" and the district never appears on the map or in the dropdowns (Faiz,
# 2026-07-01). The shared DISTRICT_I code can't distinguish the two, so reassign
# by BLOCK_ID (stable, globally unique) to match the authoritative village master
# (KAMRUP-METRO = Chandrapur, Dimoria, Ramcharani/Rani).
KAMRUP_METRO_BLOCK_IDS = frozenset({1166, 1636, 5087})  # Chandrapur, Dimoria, Rani
KAMRUP_METRO_NAME = "Kamrup Metro"


def _apply_district_overrides(gdf):
    """Correct block->district labels that the source shapefile gets wrong.

    Currently only Kamrup Metro (see KAMRUP_METRO_BLOCK_IDS). Applied AFTER the
    DISTRICT_I->name mapping so it wins. Keyed by BLOCK_ID, numeric-coerced so it
    matches whether the column is int, float or string. No-op when the expected
    columns are absent."""
    if 'BLOCK_ID' in gdf.columns and 'Dist_Name' in gdf.columns:
        bid = pd.to_numeric(gdf['BLOCK_ID'], errors='coerce')
        gdf.loc[bid.isin(KAMRUP_METRO_BLOCK_IDS), 'Dist_Name'] = KAMRUP_METRO_NAME
    return gdf


def load_shapefile():
    """Load block data: geometry from shapefile + values from Google Sheets.

    Values come from the coded block_values sheet with the end-user update
    sheet (LEAF-59) overlaid on top when published — see
    google_sheets.get_block_values_overlaid.
    """
    from google_sheets import get_block_values_overlaid

    geom_gdf = _load_shapefile_geometry()

    # Try to get values from Google Sheets (with user-update overlay applied).
    values_df = get_block_values_overlaid()

    if values_df is not None and 'BLOCK_ID' in values_df.columns:
        # Drop ID/geometry cols from values to avoid duplicates on merge
        drop_cols = ['STATE_ID', 'DISTRICT_I', 'id', 'Block_name', 'Dist_Name']
        values_df = values_df.drop(columns=[c for c in drop_cols if c in values_df.columns], errors='ignore')

        # Merge geometry with sheet values on BLOCK_ID
        gdf = geom_gdf.merge(values_df, on='BLOCK_ID', how='left')
    else:
        # Fallback: load full shapefile the old way
        shapefile_path = DATA_DIR / "4DSS_VAR_2.0.shp"
        gdf = gpd.read_file(shapefile_path)
        gdf.columns = [col.strip() for col in gdf.columns]
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
        gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.001, preserve_topology=True)

    # Add district names
    district_mapping = load_district_mapping()
    if district_mapping and 'DISTRICT_I' in gdf.columns:
        gdf['Dist_Name'] = gdf['DISTRICT_I'].map(district_mapping)

    # Correct districts the source shapefile mislabels (e.g. Kamrup Metro, whose
    # blocks share Kamrup's DISTRICT_I code). Must run after the mapping above.
    gdf = _apply_district_overrides(gdf)

    # LEAF #24: normalize block-name capitalization to Title Case so dropdowns,
    # tooltips, and headers are consistent everywhere (the source sheet mixes
    # UPPER, lower, and Title case).
    if 'Block_name' in gdf.columns:
        gdf['Block_name'] = gdf['Block_name'].apply(
            lambda x: str(x).strip().title() if pd.notna(x) else x
        )

    return gdf


def load_metadata():
    """Load the variable metadata from Google Sheets (with fallback to local CSV)."""
    from google_sheets import get_sheet
    df = get_sheet("dss_input")
    if df is None:
        # Ultimate fallback: read local CSV directly
        csv_path = DATA_DIR / "DSS_input2.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Metadata CSV not found at {csv_path}")
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        df.columns = [col.strip() for col in df.columns]
    return _overlay_livestock_subfilter(df)


def get_block_convergence(block_name):
    """07-Jun: Biophysical / Infrastructure (convergence) values for one block.

    The client tags individual variables in the dss_input sheet's SECOND
    "Cluster" column (a per-variable convergence tag they added in column P;
    pandas reads the duplicate header as ``Cluster.1``). Every row tagged
    ``Biophysical`` or ``Infrastructure`` names an ``I_variable`` whose value
    for this block (from the block_values sheet) is shown on the cluster
    drill-down's Biophysical / Infrastructure (convergence) cards.

    Returns ``{block_name, available, biophysical: [...], infrastructure: [...]}``
    where each list item is ``{code, label, value}`` (value is a rounded float,
    or None when the block has no value for that code). ``available`` is True
    once the block is found in block_values. Empty/untagged sheets yield empty
    lists so the cards show a graceful empty state rather than erroring.
    """
    result = {'block_name': block_name, 'available': False,
              'biophysical': [], 'infrastructure': []}
    try:
        meta = load_metadata()
    except Exception as e:
        print(f"[data_utils] convergence: metadata load failed: {e}")
        return result
    if meta is None:
        return result

    # Locate the convergence tag column by CONTENT, not by name. The client
    # maintains this column in the dss_input sheet and has renamed it over time
    # ("Cluster" -> duplicate read as "Cluster.1" -> "Cluster card"), so we pick
    # the non-'group' column carrying the most Biophysical / Infrastructure
    # cells. 'group' is excluded because it legitimately contains the value
    # 'Infrastructure' (a variable group) and would otherwise hijack detection.
    # Counting BOTH categories (not just 'Biophysical') keeps it working even
    # when the client tags only Infrastructure rows.
    tag_col = None
    best = 0
    for col in meta.columns:
        if col == 'group':
            continue
        vals = meta[col].astype(str).str.strip().str.lower()
        n = int(vals.isin(['biophysical', 'infrastructure']).sum())
        if n > best:
            best = n
            tag_col = col
    if tag_col is None:
        return result

    label_col = 'I_label' if 'I_label' in meta.columns else None
    tagged = {}        # code -> (tag, label); LAST tagged row wins (see below)
    conflicts = set()  # codes tagged for BOTH cards across rows
    for _, r in meta.iterrows():
        tag = str(r.get(tag_col) or '').strip().lower()
        if tag not in ('biophysical', 'infrastructure'):
            continue
        # Skip blank rows: a stray tag on a row with no I_variable must not
        # create a phantom entry. NB ``str(NaN)`` is the literal 'nan', which
        # is truthy, so an explicit isna() guard is required here.
        raw_code = r.get('I_variable')
        if raw_code is None or pd.isna(raw_code):
            continue
        code = str(raw_code).strip()
        if not code:
            continue
        # The same variable can appear on multiple dss_input rows (one per
        # intervention). When two of those rows carry DIFFERENT card tags the
        # client has left a stale tag behind; LAST-row-wins lets a later
        # corrective tag override the earlier one (the client appends fixes as
        # new rows). The conflict is recorded and surfaced by validate_sheets()
        # so the sheet can be cleaned up.
        if code in tagged and tagged[code][0] != tag:
            conflicts.add(code)
        label = str(r.get(label_col) or '').strip() if label_col else ''
        tagged[code] = (tag, label or code)
    if conflicts:
        print("[data_utils] convergence: variable(s) tagged for both cards, "
              f"using last tag: {', '.join(sorted(conflicts))}")
    if not tagged:
        return result

    from google_sheets import get_block_values_overlaid
    bv = get_block_values_overlaid()
    if bv is None or 'Block_name' not in bv.columns:
        return result
    match = bv[bv['Block_name'].astype(str).str.strip().str.lower()
               == str(block_name).strip().lower()]
    if len(match) == 0:
        return result
    bvrow = match.iloc[0]
    result['available'] = True
    for code, (tag, label) in tagged.items():
        if code not in bv.columns:
            continue
        raw = bvrow.get(code)
        if raw is None or pd.isna(raw) or str(raw).strip() == '':
            value = None
        else:
            try:
                value = round(float(raw), 2)
            except (ValueError, TypeError):
                value = raw
        entry = {'code': code, 'label': label, 'value': value}
        result['biophysical' if tag == 'biophysical' else 'infrastructure'].append(entry)
    return result


def _overlay_livestock_subfilter(df):
    """LEAF-51: add the Livestock sub-types (Dairy/Goatery/Piggery/Backyard_Poultry/
    Duckery/Fishery_Activity) so the sub-filter dropdown + per-type config work
    WITHOUT editing the client's dss_input sheet.

    Reads the committed data/livestock_subfilter.csv and APPENDS its rows
    (parent=Livestock) to the metadata in memory. It NEVER writes the sheet, so
    nothing the client maintains there is touched.

    Reversible / yields to the sheet: if the source already declares Livestock
    children (a row with parent == "Livestock"), this is a no-op — so once the
    rows are added to the sheet itself, the overlay bows out (no duplication)."""
    subtypes = set(LIVESTOCK_SUBTYPES)
    try:
        if df is None:
            return df
        # Defer ONLY if the sheet already defines the real sub-types as Livestock
        # children (then it owns them and we add nothing).
        if {'parent', 'Cluster'}.issubset(df.columns):
            liv = df[df['parent'].astype(str).str.strip().str.lower() == 'livestock']
            present = set(liv['Cluster'].astype(str).str.strip())
            if subtypes.issubset(present):
                return df
        sub_path = SUBFILTER_PATH
        if not sub_path.exists():
            return df
        sub = pd.read_csv(sub_path, encoding='utf-8-sig')
        sub.columns = [c.strip() for c in sub.columns]
        df = df.copy()
        # The sub-filter is defined solely by this overlay. Clear any stray
        # `parent` values in the source so accidental sheet edits can't mis-nest
        # the top-level interventions (in-memory only — the sheet is untouched).
        df['parent'] = pd.NA
        return pd.concat([df, sub], ignore_index=True)
    except Exception as e:
        print(f"[data_utils] livestock sub-filter overlay skipped: {e}")
        return df


# The six Livestock commodities the sub-filter is built from. The overlay only
# defers to the Google Sheet once it declares ALL of these as Livestock
# children (see _overlay_livestock_subfilter); an uploaded CSV must therefore
# define all six so the dropdown is complete in every code path.
LIVESTOCK_SUBTYPES = ["Dairy", "Goatery", "Piggery", "Backyard_Poultry",
                      "Duckery", "Fishery_Activity"]
# Columns the upload must carry. Mirrors DSS_input2 + the `parent` link column.
SUBFILTER_REQUIRED_COLS = ["Cluster", "I_variable", "range_min", "range_max", "parent"]
SUBFILTER_PATH = DATA_DIR / "livestock_subfilter.csv"


def validate_livestock_subfilter_csv(text):
    """Validate uploaded Livestock sub-filter CSV text (LEAF-51 follow-up).

    Returns (df, None) when valid, else (None, error_message). Checks:
      - parses as CSV with the required columns,
      - every parent value is "Livestock" (case-insensitive),
      - all six commodities present (so the overlay never half-fills the
        dropdown), and each has at least one variable row,
      - range_min / range_max are numeric and range_min <= range_max.
    """
    import io
    try:
        df = pd.read_csv(io.StringIO(text), encoding='utf-8-sig')
    except Exception as e:
        return None, f"Could not parse the file as CSV: {e}"
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in SUBFILTER_REQUIRED_COLS if c not in df.columns]
    if missing:
        return None, f"Missing required column(s): {', '.join(missing)}."

    df = df[df['Cluster'].notna() & (df['Cluster'].astype(str).str.strip() != "")].copy()
    if df.empty:
        return None, "The file has no data rows."

    bad_parent = df[df['parent'].astype(str).str.strip().str.lower() != 'livestock']
    if len(bad_parent):
        return None, (f"{len(bad_parent)} row(s) have a parent other than 'Livestock'. "
                      "Every sub-filter row must have parent=Livestock.")

    present = {str(c).strip() for c in df['Cluster']}
    absent = [s for s in LIVESTOCK_SUBTYPES if s not in present]
    if absent:
        return None, ("Missing rows for commodit(y/ies): " + ", ".join(absent)
                      + ". All six (" + ", ".join(LIVESTOCK_SUBTYPES)
                      + ") must be present.")

    lo = pd.to_numeric(df['range_min'], errors='coerce')
    hi = pd.to_numeric(df['range_max'], errors='coerce')
    n_bad_num = int(lo.isna().sum() + hi.isna().sum())
    if n_bad_num:
        return None, f"{n_bad_num} cell(s) in range_min/range_max are not numeric."
    n_inverted = int((lo > hi).sum())
    if n_inverted:
        return None, f"{n_inverted} row(s) have range_min greater than range_max."

    return df, None


def save_livestock_subfilter_csv(df):
    """Persist a validated sub-filter DataFrame to data/livestock_subfilter.csv.

    This is the same file the runtime overlay reads, so the new values take
    effect on the next load_metadata() call (after the dss_input cache is
    refreshed) with no redeploy. Caller must refresh the dss_input cache."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(SUBFILTER_PATH, index=False, encoding='utf-8')


def get_variable_group(df, var_code):
    """Get the group for a variable code from the CSV."""
    # Look for the variable code in the 'variable' column
    for _, row in df.iterrows():
        var = row.get('variable')
        group = row.get('group')
        if pd.notna(var) and str(var).strip() == str(var_code).strip() and pd.notna(group):
            return str(group).strip()
    return 'Other'


def _is_valid_cluster(name):
    """Check if a cluster name is a real intervention (not placeholder text)."""
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if not name:
        return False
    # Skip rows that are placeholder notes
    skip_phrases = ['new internventions', 'new interventions', 'should be possible']
    return not any(phrase in name.lower() for phrase in skip_phrases)


def get_interventions():
    """
    Auto-detect interventions from CSV Cluster column.

    Supports an optional ``parent`` column (the sub-filter, LEAF-49/50/51): a
    row whose ``Cluster`` is a sub-category (e.g. "Goatery") can declare its
    parent (e.g. "Livestock"). Parents group their children; selecting a parent
    shows its own combined config, selecting a child shows the child's config.
    When the ``parent`` column is absent the hierarchy is simply flat.

    Returns dict keyed by intervention name:
        { "key", "name", "description", "parent": <name or None>, "children": [names] }
    """
    df = load_metadata()
    has_parent_col = 'parent' in df.columns

    # Map each real cluster to its parent name (first non-empty wins).
    parent_of = {}
    for _, r in df.iterrows():
        c = r.get('Cluster')
        if pd.isna(c) or not _is_valid_cluster(str(c)):
            continue
        c = str(c).strip()
        if c in parent_of:
            continue
        p = r.get('parent') if has_parent_col else None
        parent_of[c] = str(p).strip() if (p is not None and pd.notna(p) and str(p).strip()) else None

    def _entry(name, parent):
        return {
            'key': name,
            'name': name,
            'description': f"{name} focuses on sustainable agricultural practices tailored to local conditions.",
            'parent': parent,
            'children': [],
        }

    interventions = {}
    for cluster, parent in parent_of.items():
        interventions[cluster] = _entry(cluster, parent)

    # A parent referenced by a child but having no rows of its own still needs
    # an entry so it can appear in the main dropdown.
    for cluster, parent in parent_of.items():
        if parent and parent not in interventions:
            interventions[parent] = _entry(parent, None)

    # Attach children to their parents.
    for cluster, info in interventions.items():
        p = info['parent']
        if p and p in interventions:
            interventions[p]['children'].append(cluster)

    return interventions


def get_intervention_config():
    """
    Extract intervention-specific configurations from metadata.
    Returns dict with intervention name as key and list of variable configs as value.
    """
    df = load_metadata()
    gdf = load_shapefile()

    interventions = {}

    # Build a lookup from variable code -> label/description using general definitions
    # so we can fall back when I_label is missing for new interventions
    var_label_lookup = {}
    for _, r in df.iterrows():
        v = r.get('variable')
        if pd.notna(v):
            v = str(v).strip()
            if v not in var_label_lookup:
                var_label_lookup[v] = {
                    'label': str(r['label']).strip() if pd.notna(r.get('label')) else v,
                    'description': str(r['Description']).strip() if pd.notna(r.get('Description')) else '',
                }

    for cluster in df['Cluster'].dropna().unique():
        if not _is_valid_cluster(cluster):
            continue

        cluster = str(cluster).strip()
        cluster_df = df[df['Cluster'] == cluster].copy()

        variables = []
        for _, row in cluster_df.iterrows():
            if pd.notna(row.get('I_variable')):
                field = row['I_variable']

                # Get data stats for this field
                if field in gdf.columns:
                    series = pd.to_numeric(gdf[field], errors='coerce')
                    data_min = float(series.min()) if pd.notna(series.min()) else 0
                    data_max = float(series.max()) if pd.notna(series.max()) else 100
                    data_mean = float(series.mean()) if pd.notna(series.mean()) else 50
                else:
                    data_min, data_max, data_mean = 0, 100, 50

                # Get the group for this variable from the variable-to-group mapping
                var_group = get_variable_group(df, field)

                # Read preference from CSV, default to 'moderate'
                pref = row.get('Preference', '')
                if pd.notna(pref) and str(pref).strip().lower() in ('higher', 'lower', 'moderate'):
                    preference = str(pref).strip().lower()
                else:
                    preference = 'moderate'

                # Resolve label: I_label > general variable label > field code
                if pd.notna(row.get('I_label')):
                    label = row['I_label']
                elif field in var_label_lookup:
                    label = var_label_lookup[field]['label']
                else:
                    label = field

                # Resolve description: I_description > general variable description > empty
                if pd.notna(row.get('I_description')):
                    description = row['I_description']
                elif field in var_label_lookup:
                    description = var_label_lookup[field]['description']
                else:
                    description = ''

                variables.append({
                    'field': field,
                    'range_min': float(row.get('range_min')) if pd.notna(row.get('range_min')) else data_min,
                    'range_max': float(row.get('range_max')) if pd.notna(row.get('range_max')) else data_max,
                    'weight': float(row.get('I_weight', 1)) if pd.notna(row.get('I_weight')) else 1.0,
                    'label': label,
                    'description': description,
                    'group': var_group,
                    'preference': preference,
                    'data_min': data_min,
                    'data_max': data_max,
                    'data_mean': data_mean,
                })

        interventions[cluster] = variables

    return interventions


def get_variable_metadata():
    """
    Get metadata for all variables (general definitions).
    Returns dict with variable field as key.
    """
    df = load_metadata()

    variables = {}

    for _, row in df.iterrows():
        var_field = row.get('variable')
        if pd.notna(var_field):
            variables[var_field] = {
                'field': var_field,
                'group': row.get('group', 'Other') if pd.notna(row.get('group')) else 'Other',
                'subgroup': row.get('subgroup', '') if pd.notna(row.get('subgroup')) else '',
                'label': row.get('label', var_field) if pd.notna(row.get('label')) else var_field,
                'description': row.get('Description', '') if pd.notna(row.get('Description')) else '',
                'weight': float(row.get('Weight', 1)) if pd.notna(row.get('Weight')) else 1.0,
            }

    return variables


def get_variable_groups():
    """Get unique variable groups from metadata."""
    df = load_metadata()
    groups = df['group'].dropna().unique().tolist()
    return [g for g in groups if g]


def get_blocks_geojson(gdf=None, include_geometry=True):
    """Convert GeoDataFrame to GeoJSON dict."""
    if gdf is None:
        gdf = load_shapefile()

    if include_geometry:
        return json.loads(gdf.to_json())
    else:
        # Return just properties without geometry
        features = []
        for _, row in gdf.iterrows():
            props = {k: v for k, v in row.items() if k != 'geometry'}
            # Convert numpy types to Python types
            for k, v in props.items():
                if pd.isna(v):
                    props[k] = None
                elif hasattr(v, 'item'):
                    props[k] = v.item()
            features.append({"properties": props})
        return {"features": features}


def get_block_by_id(block_id):
    """Get a single block by its ID."""
    gdf = load_shapefile()
    block = gdf[gdf['BLOCK_ID'] == block_id]
    if len(block) == 0:
        return None
    return json.loads(block.to_json())


def get_column_stats(column, level='block'):
    """Get min, max, mean for a numeric column."""
    if level == 'gp':
        gdf = load_gp_shapefile()
    else:
        gdf = load_shapefile()

    if column not in gdf.columns:
        return {'min': 0, 'max': 100, 'mean': 50}

    series = pd.to_numeric(gdf[column], errors='coerce')
    return {
        'min': float(series.min()) if pd.notna(series.min()) else 0,
        'max': float(series.max()) if pd.notna(series.max()) else 100,
        'mean': float(series.mean()) if pd.notna(series.mean()) else 50,
    }


# =============================================================================
# GP (Gram Panchayat) Level Data Loading
# =============================================================================

@lru_cache(maxsize=1)
def load_gp_block_mapping():
    """Load GP to Block mapping from Block_GPs.xlsx.

    Only returns mappings for blocks belonging to Tinsukia district.
    Block_GPs.xlsx contains blocks from ALL Assam districts, so without
    filtering, GPs with names that coincidentally match entries in other
    districts (e.g. AMBIKAPUR->Silchar, KAKOJAN->Jorhat Central) would
    be assigned incorrect block names. Tinsukia_GP_data.xlsx also has
    ~11 GP spelling mismatches vs Block_GPs.xlsx - those remain unmapped
    until the source data is corrected.
    """
    excel_path = DATA_DIR / "Block_GPs.xlsx"

    if not excel_path.exists():
        return {}

    df = pd.read_excel(excel_path)
    df.columns = [col.strip() for col in df.columns]

    # Load valid Tinsukia block names from block_values.csv
    block_csv = DATA_DIR / "block_values.csv"
    valid_blocks = set()
    if block_csv.exists():
        bv = pd.read_csv(block_csv)
        bv.columns = [col.strip() for col in bv.columns]
        valid_blocks = set(
            bv[bv['Dist_Name'] == 'Tinsukia']['Block_name']
            .str.strip().str.upper()
        )

    # The file has columns including: BLOCK NAME, GP NAME
    # Use column names for reliable access (avoid index-based access with unnamed columns)
    mapping = {}
    block_col = 'BLOCK NAME' if 'BLOCK NAME' in df.columns else None
    gp_col = 'GP NAME' if 'GP NAME' in df.columns else None

    if block_col and gp_col:
        for _, row in df.iterrows():
            block_name = row[block_col]
            gp_name = row[gp_col]

            if pd.notna(gp_name) and pd.notna(block_name):
                # Skip blocks that don't belong to Tinsukia
                if valid_blocks and str(block_name).strip().upper() not in valid_blocks:
                    continue
                mapping[str(gp_name).strip().upper()] = str(block_name).strip()

    return mapping


@lru_cache(maxsize=1)
def load_gp_data():
    """Load GP-level indicator data from Excel.

    The new file has coded column headers (Z, BF, AD, etc.) matching DSS variables.
    Row 0 contains human-readable labels; actual data starts from row 1.
    Column 0 (unnamed) is the GP name.
    """
    excel_path = DATA_DIR / "Tinsukia_GP_data.xlsx"

    if not excel_path.exists():
        return None

    df = pd.read_excel(excel_path, sheet_name=0)

    # Strip whitespace from column names
    df.columns = [str(col).strip() for col in df.columns]

    # Row 0 is labels, drop it - actual GP data starts from row 1
    df = df.iloc[1:].reset_index(drop=True)

    # Rename unnamed first column to GP_NAME
    first_col = df.columns[0]
    if first_col.startswith('Unnamed'):
        df = df.rename(columns={first_col: 'GP_NAME'})

    # Drop duplicate columns (e.g. AC.1), columns named 'nan', and trailing unnamed cols
    drop_cols = [c for c in df.columns if c.startswith('Unnamed') or c == 'nan' or c.endswith('.1')]
    df = df.drop(columns=drop_cols, errors='ignore')

    # Create VIL_COUNT alias from BW (NUMBER OF VILLAGE) if present
    if 'BW' in df.columns:
        df['VIL_COUNT'] = df['BW']

    # Add GP_CODE from Vill_Gp_join mapping (shapefile only has GP_CODE, not GP_NAME)
    mapping_path = DATA_DIR / "Vill_Gp_join.csv"
    if mapping_path.exists():
        vgj = pd.read_csv(mapping_path)
        gp_code_map = vgj.drop_duplicates(subset='GP_CODE')[['GP_NAME', 'GP_CODE']]
        gp_code_map['_join'] = gp_code_map['GP_NAME'].str.strip().str.upper()
        df['_join'] = df['GP_NAME'].str.strip().str.upper()
        df = df.merge(gp_code_map[['_join', 'GP_CODE']], on='_join', how='left')
        df = df.drop(columns=['_join'])

    # Convert numeric columns
    for col in df.columns:
        if col not in ['GP_NAME']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


@lru_cache(maxsize=1)
def load_gp_shapefile():
    """Load GP shapefile with data joined from Excel."""
    shapefile_path = DATA_DIR / "grampanchayat.shp"

    if not shapefile_path.exists():
        return None

    gdf = gpd.read_file(shapefile_path)

    # Ensure CRS is WGS84
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    # Normalize column names
    gdf.columns = [col.strip() for col in gdf.columns]

    # Convert GP_CODE to integer
    gdf['GP_CODE'] = pd.to_numeric(gdf['GP_CODE'], errors='coerce').astype('Int64')

    # Drop shapefile's VIL_COUNT before merge (Excel data has the updated version)
    if 'VIL_COUNT' in gdf.columns:
        gdf = gdf.drop(columns=['VIL_COUNT'])

    # Load and join GP data by GP_CODE
    gp_data = load_gp_data()
    if gp_data is not None:
        gp_data['GP_CODE'] = pd.to_numeric(gp_data['GP_CODE'], errors='coerce').astype('Int64')
        gdf = gdf.merge(gp_data, on='GP_CODE', how='left')

    # Add district info (all GPs are in Tinsukia for now)
    gdf['Dist_Name'] = 'Tinsukia'

    # Add Block name from GP-Block mapping
    gp_block_mapping = load_gp_block_mapping()
    gdf['Block_Name'] = gdf['GP_NAME'].apply(
        lambda x: gp_block_mapping.get(str(x).strip().upper(), '').title() if pd.notna(x) else ''
    )

    # Simplify geometries for performance
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.001, preserve_topology=True)

    return gdf


def get_gp_geojson(gdf=None, include_geometry=True):
    """Convert GP GeoDataFrame to GeoJSON dict."""
    if gdf is None:
        gdf = load_gp_shapefile()

    if gdf is None:
        return {"type": "FeatureCollection", "features": []}

    if include_geometry:
        return json.loads(gdf.to_json())
    else:
        features = []
        for _, row in gdf.iterrows():
            props = {k: v for k, v in row.items() if k != 'geometry'}
            for k, v in props.items():
                if pd.isna(v):
                    props[k] = None
                elif hasattr(v, 'item'):
                    props[k] = v.item()
            features.append({"properties": props})
        return {"features": features}


def get_gp_by_id(gp_id):
    """Get a single GP by its ID."""
    gdf = load_gp_shapefile()
    if gdf is None:
        return None

    gp = gdf[gdf['GP_CODE'] == int(gp_id)]
    if len(gp) == 0:
        return None
    return json.loads(gp.to_json())


def get_gp_locations():
    """Get list of GPs for dropdowns with block info."""
    gdf = load_gp_shapefile()
    if gdf is None:
        return []

    locations = []
    for _, row in gdf.iterrows():
        gp_name = row.get('GP_NAME', '')
        gp_code = row.get('GP_CODE', '')
        block_name = row.get('Block_Name', '')
        if pd.notna(gp_name):
            locations.append({
                'gp_name': str(gp_name),
                'gp_code': str(gp_code) if pd.notna(gp_code) else '',
                'block': str(block_name) if pd.notna(block_name) else '',
                'district': 'Tinsukia',
            })

    return locations


def get_gp_variable_metadata():
    """Get metadata for GP-level variables.

    GP column codes now match DSS variable codes, so we use the DSS CSV
    for labels, descriptions, and groups.
    """
    gp_data = load_gp_data()
    if gp_data is None:
        return {}

    # Build lookup from DSS CSV (variable code -> metadata)
    dss_meta = get_variable_metadata()

    variables = {}
    skip_cols = {'GP_NAME', 'GP_CODE', 'VIL_COUNT'}
    for col in gp_data.columns:
        if col in skip_cols:
            continue

        meta = dss_meta.get(col, {})
        if meta:
            variables[col] = {
                'field': col,
                'label': meta.get('label', col),
                'description': meta.get('description', col),
                'group': meta.get('group', 'Other'),
            }
        else:
            # Fallback for variables not in DSS CSV
            variables[col] = {
                'field': col,
                'label': col,
                'description': col,
                'group': categorize_gp_variable(col),
            }

    return variables


def categorize_gp_variable(col_name):
    """Categorize GP variable into groups based on name."""
    col_lower = col_name.lower()

    if any(x in col_lower for x in ['poultry', 'pig', 'cattle', 'buffalo', 'goat', 'sheep', 'horse', 'donkey', 'camel', 'mule', 'livestock']):
        return 'Livestock'
    elif any(x in col_lower for x in ['veterinary', 'milk collection']):
        return 'Livestock Services'
    elif any(x in col_lower for x in ['road', 'transport', 'railway']):
        return 'Transport & Connectivity'
    elif any(x in col_lower for x in ['bank', 'atm', 'market', 'mandies']):
        return 'Finance & Markets'
    elif any(x in col_lower for x in ['electricity', 'internet', 'telephone', 'broadband']):
        return 'Utilities'
    elif any(x in col_lower for x in ['fodder', 'crop', 'pasture', 'grazing']):
        return 'Land & Agriculture'
    elif any(x in col_lower for x in ['shg', 'shgs']):
        return 'Collectives'
    elif any(x in col_lower for x in ['duckery', 'farming', 'fishery', 'goatery', 'piggery', 'poultry_activity']):
        return 'Activities'
    else:
        return 'Other'
