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


def get_intervention_config():
    """
    Extract intervention-specific configurations from metadata.
    Returns dict with intervention name as key and list of variable configs as value.
    """
    df = load_metadata()
    gdf = load_shapefile()

    interventions = {}

    for cluster in df['Cluster'].dropna().unique():
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

                variables.append({
                    'field': field,
                    'range_min': float(row.get('range_min')) if pd.notna(row.get('range_min')) else data_min,
                    'range_max': float(row.get('range_max')) if pd.notna(row.get('range_max')) else data_max,
                    'weight': float(row.get('I_weight', 1)) if pd.notna(row.get('I_weight')) else 1.0,
                    'label': row.get('I_label', field) if pd.notna(row.get('I_label')) else field,
                    'description': row.get('I_description', '') if pd.notna(row.get('I_description')) else '',
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


def get_column_stats(column):
    """Get min, max, mean for a numeric column."""
    gdf = load_shapefile()

    if column not in gdf.columns:
        return {'min': 0, 'max': 100, 'mean': 50}

    series = pd.to_numeric(gdf[column], errors='coerce')
    return {
        'min': float(series.min()) if pd.notna(series.min()) else 0,
        'max': float(series.max()) if pd.notna(series.max()) else 100,
        'mean': float(series.mean()) if pd.notna(series.mean()) else 50,
    }
