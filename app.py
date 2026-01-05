"""
LEAF DSS - Flask Application
Decision Support System for Agricultural Interventions
"""

import os
import json
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
import pandas as pd

from config import COLORS, FEASIBILITY_COLORS, INTERVENTIONS, VARIABLE_GROUPS, MAP_CONFIG
from data_utils import (
    load_shapefile,
    load_metadata,
    get_intervention_config,
    get_variable_metadata,
    get_variable_groups,
    get_blocks_geojson,
    get_block_by_id,
    get_column_stats,
)
from feasibility import (
    add_feasibility_to_gdf,
    get_feasibility_distribution,
    get_feasibility_stats,
    calculate_and_get_geojson,
)

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'leaf-dss-secret-key')


# =============================================================================
# Page Routes
# =============================================================================

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html',
                           interventions=INTERVENTIONS,
                           variable_groups=VARIABLE_GROUPS,
                           colors=COLORS,
                           map_config=MAP_CONFIG)


# =============================================================================
# Data Loading APIs
# =============================================================================

@app.route('/api/blocks')
def api_blocks():
    """Return all blocks as GeoJSON."""
    try:
        gdf = load_shapefile()
        geojson = get_blocks_geojson(gdf)
        return jsonify(geojson)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/locations')
def api_locations():
    """Return list of states and blocks for dropdowns."""
    try:
        gdf = load_shapefile()

        blocks = []
        for _, row in gdf.iterrows():
            # State name - hardcoded as Assam since shapefile only has STATE_ID
            state_name = 'Assam'

            # Block_name contains the block names
            block_name = None
            for col in ['Block_name', 'BLOCK', 'block', 'Block']:
                if col in row and pd.notna(row[col]):
                    block_name = str(row[col])
                    break

            if block_name:  # Only add if we have a block name
                blocks.append({
                    'state': state_name,
                    'block_name': block_name,
                })

        return jsonify({'blocks': blocks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/blocks/<block_id>')
def api_block_detail(block_id):
    """Return single block details."""
    try:
        block = get_block_by_id(block_id)
        if block is None:
            return jsonify({'error': 'Block not found'}), 404
        return jsonify(block)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/interventions')
def api_interventions():
    """List available interventions."""
    try:
        interventions_list = [
            {
                'key': key,
                'name': val['name'],
                'description': val['description']
            }
            for key, val in INTERVENTIONS.items()
        ]
        return jsonify({'interventions': interventions_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/intervention/<name>/config')
def api_intervention_config(name):
    """Get configuration for a specific intervention."""
    try:
        config = get_intervention_config()

        if name not in config:
            return jsonify({'error': f'Intervention "{name}" not found'}), 404

        variables = config[name]
        intervention_info = INTERVENTIONS.get(name, {})

        return jsonify({
            'intervention': name,
            'name': intervention_info.get('name', name),
            'description': intervention_info.get('description', ''),
            'variables': variables
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/variable-groups')
def api_variable_groups():
    """List available variable groups."""
    try:
        groups = get_variable_groups()
        return jsonify({'groups': groups})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/variables')
def api_variables():
    """Get all variable metadata."""
    try:
        variables = get_variable_metadata()
        return jsonify({'variables': variables})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/variable-stats/<variable>')
def api_variable_stats(variable):
    """Get min/max/mean for a variable."""
    try:
        stats = get_column_stats(variable)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Feasibility Calculation APIs
# =============================================================================

@app.route('/api/calculate-feasibility', methods=['POST'])
def api_calculate_feasibility():
    """
    Calculate feasibility scores with custom filters.

    Request body:
    {
        "intervention": "Organic Farming",  // optional
        "filters": [
            { "column": "AD", "min_val": 20, "max_val": 60, "weight": 1.0 }
        ],
        "logic": "AND"  // or "OR"
    }
    """
    try:
        data = request.get_json()

        intervention = data.get('intervention')
        filters = data.get('filters', [])
        logic = data.get('logic', 'AND')

        # If intervention specified but no filters, use default intervention config
        if intervention and not filters:
            config = get_intervention_config()
            if intervention in config:
                filters = [
                    {
                        'column': v['field'],
                        'min_val': v['range_min'],
                        'max_val': v['range_max'],
                        'weight': v['weight']
                    }
                    for v in config[intervention]
                ]

        # Load data and calculate
        gdf = load_shapefile()
        result = calculate_and_get_geojson(gdf, filters, logic)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/statistics')
def api_statistics():
    """Get distribution statistics for current data."""
    try:
        gdf = load_shapefile()
        stats = {
            'total_blocks': len(gdf),
            'columns': list(gdf.columns),
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Export API
# =============================================================================

@app.route('/api/export/csv', methods=['POST'])
def api_export_csv():
    """Export filtered data as CSV."""
    try:
        data = request.get_json()

        intervention = data.get('intervention')
        filters = data.get('filters', [])
        logic = data.get('logic', 'AND')

        # If intervention specified but no filters, use default
        if intervention and not filters:
            config = get_intervention_config()
            if intervention in config:
                filters = [
                    {
                        'column': v['field'],
                        'min_val': v['range_min'],
                        'max_val': v['range_max'],
                        'weight': v['weight']
                    }
                    for v in config[intervention]
                ]

        # Load and calculate
        gdf = load_shapefile()

        if filters:
            gdf = add_feasibility_to_gdf(gdf, filters, logic)

        # Remove geometry for CSV export
        df = gdf.drop(columns=['geometry'])

        # Convert to CSV
        csv_data = df.to_csv(index=False)

        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=leaf_data.csv'}
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Configuration API
# =============================================================================

@app.route('/api/config')
def api_config():
    """Get app configuration (colors, thresholds, etc.)."""
    return jsonify({
        'colors': COLORS,
        'feasibility_colors': FEASIBILITY_COLORS,
        'map_config': MAP_CONFIG,
    })


# =============================================================================
# Health Check
# =============================================================================

@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=5000, debug=True)
