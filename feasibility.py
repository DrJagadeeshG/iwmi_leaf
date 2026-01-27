"""
Feasibility Calculator
Calculates feasibility scores based on weighted criteria matching
"""

import pandas as pd
import numpy as np
import json
from config import FEASIBILITY_COLORS, FEASIBILITY_THRESHOLDS


def calculate_criteria_match(gdf, column, min_val, max_val):
    """
    Check if values fall within the specified range.
    Returns Series: 1 if within range, 0 if outside, NaN if no data.
    """
    if column not in gdf.columns:
        return pd.Series([np.nan] * len(gdf), index=gdf.index)

    series = pd.to_numeric(gdf[column], errors='coerce')

    # Create match series
    match = pd.Series(np.nan, index=gdf.index)
    valid_mask = series.notna()

    match[valid_mask] = ((series[valid_mask] >= min_val) &
                          (series[valid_mask] <= max_val)).astype(float)

    return match


def calculate_feasibility(gdf, criteria, logic="AND"):
    """
    Calculate feasibility percentage (0-100) for each block.

    Args:
        gdf: GeoDataFrame with block data
        criteria: List of dicts with column, min_val, max_val, weight
        logic: "AND" or "OR"

    Returns:
        Series with feasibility percentages (0-100)
    """
    if not criteria:
        return pd.Series([np.nan] * len(gdf), index=gdf.index)

    weighted_matches = pd.Series(0.0, index=gdf.index)
    weighted_applicable = pd.Series(0.0, index=gdf.index)

    for c in criteria:
        column = c.get('column') or c.get('field')
        min_val = c.get('min_val', c.get('range_min', float('-inf')))
        max_val = c.get('max_val', c.get('range_max', float('inf')))
        weight = c.get('weight', 1)

        if column is None:
            continue

        # Handle None values
        if pd.isna(min_val):
            min_val = float('-inf')
        if pd.isna(max_val):
            max_val = float('inf')

        match = calculate_criteria_match(gdf, column, min_val, max_val)

        # Add to weighted sums
        valid_mask = match.notna()
        weighted_matches[valid_mask] += match[valid_mask] * weight
        weighted_applicable[valid_mask] += weight

    # Calculate percentage
    feasibility = pd.Series(np.nan, index=gdf.index)
    applicable_mask = weighted_applicable > 0

    feasibility[applicable_mask] = (
        weighted_matches[applicable_mask] /
        weighted_applicable[applicable_mask] * 100
    )

    return feasibility


def classify_feasibility(value):
    """
    Classify a feasibility value into a category.
    Returns tuple of (category_key, display_label)
    """
    if pd.isna(value):
        return ('no_data', 'No Data')

    try:
        value = float(value)
    except:
        return ('no_data', 'No Data')

    # Classify based on thresholds
    if value >= 100:
        return ('very_high', '100%')
    elif value >= 75:
        return ('high', '75-100%')
    elif value >= 50:
        return ('moderate_high', '50-75%')
    elif value >= 25:
        return ('moderate', '25-50%')
    elif value >= 1:
        return ('low', '1-25%')
    else:
        return ('very_low', '0%')


def get_feasibility_color(value):
    """Get the color for a feasibility value."""
    category, _ = classify_feasibility(value)
    return FEASIBILITY_COLORS.get(category, FEASIBILITY_COLORS['no_data'])


def add_feasibility_to_gdf(gdf, criteria, logic="AND"):
    """
    Add feasibility score and classification to GeoDataFrame.

    Returns GeoDataFrame with added columns:
        - feasibility: numeric score (0-100)
        - feasibility_class: category key
        - feasibility_label: display label
        - feasibility_color: hex color
    """
    gdf = gdf.copy()

    gdf['feasibility'] = calculate_feasibility(gdf, criteria, logic)

    classifications = gdf['feasibility'].apply(classify_feasibility)
    gdf['feasibility_class'] = classifications.apply(lambda x: x[0])
    gdf['feasibility_label'] = classifications.apply(lambda x: x[1])
    gdf['feasibility_color'] = gdf['feasibility'].apply(get_feasibility_color)

    return gdf


def get_feasibility_distribution(gdf):
    """
    Get count of blocks in each feasibility category.
    Returns dict with category labels as keys and counts as values.
    """
    if 'feasibility_label' not in gdf.columns:
        return {}

    distribution = gdf['feasibility_label'].value_counts().to_dict()

    # Ensure all categories are present
    all_labels = ['100%', '75-100%', '50-75%', '25-50%', '1-25%', '0%', 'No Data']
    for label in all_labels:
        if label not in distribution:
            distribution[label] = 0

    return distribution


def get_feasibility_stats(gdf):
    """Get summary statistics for feasibility scores."""
    if 'feasibility' not in gdf.columns:
        return {}

    valid = gdf['feasibility'].dropna()

    return {
        'total_blocks': int(len(gdf)),
        'blocks_with_data': int(len(valid)),
        'blocks_no_data': int(len(gdf) - len(valid)),
        'mean': float(valid.mean()) if len(valid) > 0 else 0,
        'median': float(valid.median()) if len(valid) > 0 else 0,
        'min': float(valid.min()) if len(valid) > 0 else 0,
        'max': float(valid.max()) if len(valid) > 0 else 100,
        'high_feasibility': int((valid >= 75).sum()),
        'low_feasibility': int((valid < 25).sum()),
    }


def calculate_and_get_geojson(gdf, criteria, logic="AND", district=None):
    """
    Calculate feasibility and return as GeoJSON with statistics.

    Args:
        gdf: GeoDataFrame with block data
        criteria: List of filter criteria
        logic: "AND" or "OR"
        district: Optional district ID to filter statistics
    """
    # Add feasibility scores to all blocks
    gdf_with_feas = add_feasibility_to_gdf(gdf, criteria, logic)

    # Filter by district for statistics if specified
    if district:
        # Try matching by district name first (frontend sends names like "Tinsukia"),
        # fall back to DISTRICT_I for numeric IDs
        if 'Dist_Name' in gdf_with_feas.columns:
            gdf_for_stats = gdf_with_feas[gdf_with_feas['Dist_Name'] == district]
        else:
            gdf_for_stats = gdf_with_feas[gdf_with_feas['DISTRICT_I'].astype(str) == str(district)]
        # If no match by name, try by ID as fallback
        if len(gdf_for_stats) == 0 and 'DISTRICT_I' in gdf_with_feas.columns:
            gdf_for_stats = gdf_with_feas[gdf_with_feas['DISTRICT_I'].astype(str) == str(district)]
    else:
        gdf_for_stats = gdf_with_feas

    # Get distribution and stats (filtered by district if specified)
    distribution = get_feasibility_distribution(gdf_for_stats)
    stats = get_feasibility_stats(gdf_for_stats)

    # Convert full GeoJSON (all blocks for map display)
    geojson = json.loads(gdf_with_feas.to_json())

    # Clean up NaN values in properties
    for feature in geojson['features']:
        props = feature['properties']
        for key, value in props.items():
            if pd.isna(value) if isinstance(value, float) else False:
                props[key] = None

    return {
        'geojson': geojson,
        'statistics': {
            **stats,
            'distribution': distribution
        }
    }
