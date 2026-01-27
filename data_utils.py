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
def load_district_mapping():
    """Load district ID to name mapping from Block_assam shapefile."""
    block_assam_path = DATA_DIR / "Block_assam.shp"

    if not block_assam_path.exists():
        return {}

    block_assam = gpd.read_file(block_assam_path)
    return dict(zip(block_assam['DISTRICT_I'], block_assam['Dist_name']))


@lru_cache(maxsize=1)
def load_shapefile():
    """Load the shapefile with block geometries and data."""
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

    # Add district names by mapping DISTRICT_I to Dist_Name
    district_mapping = load_district_mapping()
    if district_mapping and 'DISTRICT_I' in gdf.columns:
        gdf['Dist_Name'] = gdf['DISTRICT_I'].map(district_mapping)

    # Simplify geometries for better performance
    gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.001, preserve_topology=True)

    return gdf


@lru_cache(maxsize=1)
def load_metadata():
    """Load the variable metadata CSV."""
    csv_path = DATA_DIR / "DSS_input2.csv"

    if not csv_path.exists():
        raise FileNotFoundError(f"Metadata CSV not found at {csv_path}")

    df = pd.read_csv(csv_path, encoding='utf-8-sig')

    # Normalize column names
    df.columns = [col.strip() for col in df.columns]

    return df


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
    Returns dict: { "Organic Farming": { "key": "...", "name": "...", "description": "..." } }
    """
    df = load_metadata()
    interventions = {}

    for cluster in df['Cluster'].dropna().unique():
        if not _is_valid_cluster(cluster):
            continue
        cluster = str(cluster).strip()
        interventions[cluster] = {
            'key': cluster,
            'name': cluster,
            'description': f"{cluster} focuses on sustainable agricultural practices tailored to local conditions.",
        }

    return interventions


def get_intervention_config():
    """
    Extract intervention-specific configurations from metadata.
    Returns dict with intervention name as key and list of variable configs as value.
    """
    df = load_metadata()
    gdf = load_shapefile()

    interventions = {}

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

                variables.append({
                    'field': field,
                    'range_min': float(row.get('range_min')) if pd.notna(row.get('range_min')) else data_min,
                    'range_max': float(row.get('range_max')) if pd.notna(row.get('range_max')) else data_max,
                    'weight': float(row.get('I_weight', 1)) if pd.notna(row.get('I_weight')) else 1.0,
                    'label': row.get('I_label', field) if pd.notna(row.get('I_label')) else field,
                    'description': row.get('I_description', '') if pd.notna(row.get('I_description')) else '',
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
    """Load GP to Block mapping from Block_GPs.xlsx."""
    excel_path = DATA_DIR / "Block_GPs.xlsx"

    if not excel_path.exists():
        return {}

    df = pd.read_excel(excel_path)
    df.columns = [col.strip() for col in df.columns]

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

    # Row 0 is labels, drop it — actual GP data starts from row 1
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
