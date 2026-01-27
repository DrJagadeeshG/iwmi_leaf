"""
LEAF DSS - Flask Application
Decision Support System for Agricultural Interventions
"""

import os
import json
from flask import Flask, render_template, jsonify, request, Response, send_from_directory
from flask_cors import CORS
import pandas as pd

from config import COLORS, FEASIBILITY_COLORS, VARIABLE_GROUPS, MAP_CONFIG
from data_utils import (
    load_shapefile,
    load_metadata,
    get_interventions,
    get_intervention_config,
    get_variable_metadata,
    get_variable_groups,
    get_blocks_geojson,
    get_block_by_id,
    get_column_stats,
    # GP-level functions
    load_gp_shapefile,
    get_gp_geojson,
    get_gp_by_id,
    get_gp_locations,
    get_gp_variable_metadata,
)
from feasibility import (
    add_feasibility_to_gdf,
    get_feasibility_distribution,
    get_feasibility_stats,
    calculate_and_get_geojson,
)

# RAG utilities for AI recommendations (lazy import to avoid startup delay)
rag_utils = None
def get_rag_utils():
    global rag_utils
    if rag_utils is None:
        try:
            from rag_utils import generate_recommendation, initialize_vectorstore
            rag_utils = {'generate': generate_recommendation, 'init': initialize_vectorstore}
        except ImportError as e:
            print(f"RAG utilities not available: {e}")
            rag_utils = {'error': str(e)}
    return rag_utils

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'leaf-dss-secret-key')


# =============================================================================
# Page Routes
# =============================================================================

def render_app(level='block', district='', block='', gp=''):
    """Common render function for the app."""
    return render_template('index.html',
                           interventions=get_interventions(),
                           variable_groups=VARIABLE_GROUPS,
                           colors=COLORS,
                           map_config=MAP_CONFIG,
                           initial_level=level,
                           initial_district=district,
                           initial_block=block,
                           initial_gp=gp)


@app.route('/')
def index():
    """Main dashboard page."""
    return render_app()


@app.route('/<district>')
def district_view(district):
    """District level view (shows all blocks in district)."""
    # Validate district exists
    gdf = load_shapefile()
    valid_districts = gdf['Dist_Name'].dropna().unique().tolist()
    if district not in valid_districts:
        if district in ['api', 'static', 'health']:
            return jsonify({'error': 'Invalid route'}), 404
    return render_app(level='block', district=district)


@app.route('/<district>/<block>')
def block_detail_view(district, block):
    """Block detail view: /district/block."""
    return render_app(level='block', district=district, block=block)


@app.route('/<district>/<block>/<gp>')
def gp_detail_view(district, block, gp):
    """GP detail view: /district/block/gp_name."""
    return render_app(level='gp', district=district, block=block, gp=gp)


# =============================================================================
# Data Loading APIs - Block Level
# =============================================================================

@app.route('/api/blocks')
@app.route('/api/blocks/geojson')
def api_blocks():
    """Return all blocks as GeoJSON."""
    try:
        gdf = load_shapefile()
        geojson = get_blocks_geojson(gdf)
        return jsonify(geojson)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/blocks/<block_id>')
def api_block_detail(block_id):
    """Return single block details by BLOCK_ID."""
    try:
        block = get_block_by_id(block_id)
        if block is None:
            return jsonify({'error': 'Block not found'}), 404
        return jsonify(block)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/blocks/by-name/<block_name>')
def api_block_by_name(block_name):
    """Return single block details by name."""
    try:
        gdf = load_shapefile()
        block = gdf[gdf['Block_name'] == block_name]
        if len(block) == 0:
            return jsonify({'error': 'Block not found'}), 404
        return jsonify(json.loads(block.to_json()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Location APIs - Unified location data
# =============================================================================

@app.route('/api/locations')
def api_locations():
    """Return hierarchical list of districts, blocks, and GPs for dropdowns."""
    try:
        gdf = load_shapefile()
        gp_gdf = load_gp_shapefile()

        # Build districts with blocks
        districts = {}
        for _, row in gdf.iterrows():
            district_name = row.get('Dist_Name')
            block_name = row.get('Block_name')

            if pd.notna(district_name):
                district_name = str(district_name)
                if district_name not in districts:
                    districts[district_name] = {
                        'name': district_name,
                        'blocks': [],
                        'has_gp_data': False
                    }

                if pd.notna(block_name):
                    block_name = str(block_name)
                    if block_name not in [b['name'] for b in districts[district_name]['blocks']]:
                        districts[district_name]['blocks'].append({
                            'name': block_name,
                            'gps': []
                        })

        # Add GP data if available
        if gp_gdf is not None:
            gp_district = 'Tinsukia'  # Currently only Tinsukia has GP data
            if gp_district in districts:
                districts[gp_district]['has_gp_data'] = True

                # Group GPs by block
                for _, row in gp_gdf.iterrows():
                    gp_name = row.get('GP_NAME')
                    block_name = row.get('Block_Name')
                    gp_code = row.get('GP_CODE')

                    if pd.notna(gp_name) and pd.notna(block_name):
                        # Find or create block
                        block_found = False
                        for block in districts[gp_district]['blocks']:
                            if block['name'] == block_name:
                                block['gps'].append({
                                    'name': str(gp_name),
                                    'code': str(gp_code) if pd.notna(gp_code) else None
                                })
                                block_found = True
                                break

                        if not block_found:
                            districts[gp_district]['blocks'].append({
                                'name': str(block_name),
                                'gps': [{
                                    'name': str(gp_name),
                                    'code': str(gp_code) if pd.notna(gp_code) else None
                                }]
                            })

        # Convert to sorted list
        result = sorted(districts.values(), key=lambda x: (not x['has_gp_data'], x['name']))

        # Also return flat blocks list for backward compatibility
        blocks = []
        for district in result:
            for block in district['blocks']:
                blocks.append({
                    'district': district['name'],
                    'block_name': block['name']
                })

        return jsonify({
            'districts': result,
            'blocks': blocks  # Backward compatibility
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/districts')
def api_districts():
    """Return list of all districts with metadata."""
    try:
        gdf = load_shapefile()
        gp_gdf = load_gp_shapefile()

        districts = {}
        for _, row in gdf.iterrows():
            district_name = row.get('Dist_Name')
            if pd.notna(district_name):
                district_name = str(district_name)
                if district_name not in districts:
                    districts[district_name] = {
                        'name': district_name,
                        'block_count': 0,
                        'has_gp_data': False
                    }
                districts[district_name]['block_count'] += 1

        # Check GP availability
        if gp_gdf is not None:
            gp_district = 'Tinsukia'
            if gp_district in districts:
                districts[gp_district]['has_gp_data'] = True
                districts[gp_district]['gp_count'] = len(gp_gdf)

        result = sorted(districts.values(), key=lambda x: (not x['has_gp_data'], x['name']))
        return jsonify({'districts': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/districts/<district>/blocks')
def api_district_blocks(district):
    """Return all blocks in a specific district."""
    try:
        gdf = load_shapefile()
        district_blocks = gdf[gdf['Dist_Name'] == district]

        if len(district_blocks) == 0:
            return jsonify({'error': f'District "{district}" not found'}), 404

        blocks = []
        for _, row in district_blocks.iterrows():
            block_name = row.get('Block_name')
            if pd.notna(block_name):
                blocks.append({
                    'name': str(block_name),
                    'district': district
                })

        return jsonify({
            'district': district,
            'blocks': sorted(blocks, key=lambda x: x['name'])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Backward compatibility aliases
@app.route('/api/district/names')
def api_district_names():
    """Return list of all district names (deprecated - use /api/districts)."""
    return api_districts()


@app.route('/api/block/names')
def api_block_names():
    """Return list of all block names (deprecated - use /api/locations)."""
    try:
        gdf = load_shapefile()
        names = []
        for _, row in gdf.iterrows():
            block_name = row.get('Block_name')
            district_name = row.get('Dist_Name')
            if pd.notna(block_name):
                names.append({
                    'name': str(block_name),
                    'district': str(district_name) if pd.notna(district_name) else None
                })
        return jsonify({'names': sorted(names, key=lambda x: x['name'])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/names')
def api_gp_names():
    """Return list of all GP names."""
    try:
        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'names': []})

        names = []
        for _, row in gdf.iterrows():
            gp_name = row.get('GP_NAME')
            gp_code = row.get('GP_CODE')
            block_name = row.get('Block_Name')
            vil_count = row.get('VIL_COUNT') or row.get('NUMBER OF VILLAGE')
            if pd.notna(gp_name):
                names.append({
                    'name': str(gp_name),
                    'code': str(gp_code) if pd.notna(gp_code) else None,
                    'block': str(block_name) if pd.notna(block_name) else None,
                    'village_count': int(vil_count) if pd.notna(vil_count) else None,
                    'district': 'Tinsukia'
                })
        return jsonify({'names': sorted(names, key=lambda x: x['name'])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/interventions')
def api_interventions():
    """List available interventions (auto-detected from CSV)."""
    try:
        interventions = get_interventions()
        interventions_list = [
            {
                'key': val['key'],
                'name': val['name'],
                'description': val['description']
            }
            for val in interventions.values()
        ]
        return jsonify({'interventions': interventions_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/variables')
def api_variables():
    """Get all available variables from the shapefile."""
    try:
        gdf = load_shapefile()
        metadata = get_variable_metadata()

        # Load CSV to get group info
        csv_df = load_metadata()
        # Create a mapping of variable to group (use 'variable' column, not 'I_variable')
        var_to_group = {}
        for _, row in csv_df.iterrows():
            var = row.get('variable')
            group = row.get('group')
            if pd.notna(var) and pd.notna(group) and var not in var_to_group:
                var_to_group[str(var).strip()] = str(group).strip()

        variables = []
        # Get numeric columns from shapefile
        for col in gdf.columns:
            if col in ['geometry', 'BLOCK_ID', 'STATE_ID', 'DISTRICT_I', 'Block_name', 'id']:
                continue

            series = pd.to_numeric(gdf[col], errors='coerce')
            if series.notna().sum() > 0:  # Has numeric data
                meta = metadata.get(col, {})
                variables.append({
                    'field': col,
                    'label': meta.get('label', col),
                    'description': meta.get('description', ''),
                    'group': var_to_group.get(col, 'Other'),
                    'data_min': float(series.min()) if pd.notna(series.min()) else 0,
                    'data_max': float(series.max()) if pd.notna(series.max()) else 100,
                    'data_mean': float(series.mean()) if pd.notna(series.mean()) else 50,
                })

        return jsonify(variables)
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
        interventions = get_interventions()
        intervention_info = interventions.get(name, {})

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
        "logic": "AND",  // or "OR"
        "district": "134"  // optional district ID to filter statistics
    }
    """
    try:
        data = request.get_json()

        intervention = data.get('intervention')
        filters = data.get('filters', [])
        logic = data.get('logic', 'AND')
        district = data.get('district')

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
        result = calculate_and_get_geojson(gdf, filters, logic, district)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai-recommendation', methods=['POST'])
def api_ai_recommendation():
    """
    Generate AI-powered recommendations based on block data and policy documents.

    Request body:
    {
        "block_name": "Digboi",
        "district_name": "Tinsukia",
        "intervention": "Organic Farming",
        "feasibility_score": 65.5,
        "metrics": [
            {"label": "Agricultural Land %", "value": 45.2, "in_range": true, "min": 30, "max": 70},
            {"label": "Water Availability", "value": 15.0, "in_range": false, "min": 20, "max": 50}
        ],
        "filters": [...]  // Active filter configurations
    }
    """
    try:
        rag = get_rag_utils()

        if 'error' in rag:
            return jsonify({
                'recommendation': 'AI recommendations are not available. Please install RAG dependencies.',
                'error': rag['error'],
                'sources': []
            }), 503

        data = request.get_json()

        block_name = data.get('block_name', 'Unknown')
        district_name = data.get('district_name', 'Unknown')
        intervention = data.get('intervention', '')
        feasibility_score = data.get('feasibility_score', 0)
        metrics = data.get('metrics', [])
        filters = data.get('filters', [])

        if not intervention:
            return jsonify({
                'recommendation': 'Please select an intervention to get AI recommendations.',
                'sources': []
            })

        result = rag['generate'](
            block_name=block_name,
            district_name=district_name,
            intervention=intervention,
            feasibility_score=feasibility_score,
            metrics=metrics,
            filters=filters
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'recommendation': f'Error generating recommendation: {str(e)}',
            'error': str(e),
            'sources': []
        }), 500


@app.route('/api/ai-recommendation/init', methods=['POST'])
def api_init_vectorstore():
    """Initialize/rebuild the vector store from PDF documents."""
    try:
        rag = get_rag_utils()

        if 'error' in rag:
            return jsonify({'success': False, 'error': rag['error']}), 503

        success = rag['init']()
        return jsonify({'success': success})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/statistics')
@app.route('/api/blocks/statistics')
def api_statistics():
    """Get distribution statistics for block data."""
    try:
        gdf = load_shapefile()

        # Count by district
        district_counts = gdf.groupby('Dist_Name').size().to_dict() if 'Dist_Name' in gdf.columns else {}

        stats = {
            'total_blocks': len(gdf),
            'districts': district_counts,
            'district_count': len(district_counts),
            'columns': [c for c in gdf.columns if c != 'geometry'],
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
# GP (Gram Panchayat) Level APIs
# =============================================================================

@app.route('/api/gp')
@app.route('/api/gp/geojson')
def api_gp_geojson():
    """Return all GPs as GeoJSON."""
    try:
        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404
        geojson = get_gp_geojson(gdf)
        return jsonify(geojson)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/locations')
def api_gp_locations():
    """Return list of GPs grouped by block for dropdowns."""
    try:
        locations = get_gp_locations()

        # Group by block using the block info already in locations
        by_block = {}
        for loc in locations:
            block_name = loc.get('block', '')
            if block_name not in by_block:
                by_block[block_name] = []
            by_block[block_name].append(loc)

        return jsonify({
            'gps': locations,  # Flat list for backward compatibility
            'by_block': by_block  # Grouped by block
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/<gp_id>')
def api_gp_detail(gp_id):
    """Return single GP details by GP_CODE."""
    try:
        gp = get_gp_by_id(gp_id)
        if gp is None:
            return jsonify({'error': 'GP not found'}), 404
        return jsonify(gp)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/by-name/<gp_name>')
def api_gp_by_name(gp_name):
    """Return single GP details by name."""
    try:
        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404

        gp = gdf[gdf['GP_NAME'] == gp_name]
        if len(gp) == 0:
            return jsonify({'error': 'GP not found'}), 404
        return jsonify(json.loads(gp.to_json()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/block/<block_name>')
def api_gp_by_block(block_name):
    """Return all GPs in a specific block."""
    try:
        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404

        block_gps = gdf[gdf['Block_Name'] == block_name]
        if len(block_gps) == 0:
            return jsonify({'error': f'No GPs found in block "{block_name}"'}), 404

        gps = []
        for _, row in block_gps.iterrows():
            gps.append({
                'name': row.get('GP_NAME'),
                'code': str(row.get('GP_CODE')) if pd.notna(row.get('GP_CODE')) else None,
                'village_count': int(row.get('VIL_COUNT') or row.get('NUMBER OF VILLAGE') or 0)
            })

        return jsonify({
            'block': block_name,
            'district': 'Tinsukia',
            'gps': sorted(gps, key=lambda x: x['name'] or '')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/variables')
def api_gp_variables():
    """Get all available GP-level variables."""
    try:
        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404

        metadata = get_gp_variable_metadata()

        variables = []
        for col in gdf.columns:
            if col in ['geometry', 'GP_CODE', 'GP_ID', 'GP_NAME', 'VIL_COUNT', 'Dist_Name', 'Block_Name', 'NUMBER OF VILLAGE']:
                continue

            series = pd.to_numeric(gdf[col], errors='coerce')
            if series.notna().sum() > 0:
                meta = metadata.get(col, {})
                variables.append({
                    'field': col,
                    'label': meta.get('label', col),
                    'description': meta.get('description', col),
                    'group': meta.get('group', 'Other'),
                    'data_min': float(series.min()) if pd.notna(series.min()) else 0,
                    'data_max': float(series.max()) if pd.notna(series.max()) else 100,
                    'data_mean': float(series.mean()) if pd.notna(series.mean()) else 50,
                })

        return jsonify(variables)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/calculate-feasibility', methods=['POST'])
def api_gp_calculate_feasibility():
    """Calculate feasibility scores for GP level."""
    try:
        data = request.get_json()

        filters = data.get('filters', [])
        logic = data.get('logic', 'AND')
        block = data.get('block')  # Optional block filter

        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404

        # Filter by block if specified
        if block:
            gdf = gdf[gdf['Block_Name'] == block].copy()

        result = calculate_and_get_geojson(gdf, filters, logic, district=None)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/statistics')
def api_gp_statistics():
    """Get statistics for GP data."""
    try:
        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404

        # Count by block
        block_counts = gdf.groupby('Block_Name').size().to_dict() if 'Block_Name' in gdf.columns else {}

        stats = {
            'total_gps': len(gdf),
            'district': 'Tinsukia',
            'blocks': block_counts,
            'columns': [c for c in gdf.columns if c != 'geometry'],
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/levels')
def api_levels():
    """Return available data levels and districts with GP support."""
    gdf = load_shapefile()
    gp_gdf = load_gp_shapefile()
    gp_available = gp_gdf is not None

    # Get districts with GP data
    gp_districts = []
    if gp_available:
        gp_districts = ['Tinsukia']  # Currently only Tinsukia

    return jsonify({
        'levels': [
            {'id': 'block', 'name': 'Block', 'available': True},
            {'id': 'gp', 'name': 'Gram Panchayat', 'available': gp_available, 'districts': gp_districts},
        ],
        'gp_districts': gp_districts
    })


# =============================================================================
# Health Check & API Info
# =============================================================================

@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


@app.route('/ai-docs/<path:filename>')
def serve_ai_docs(filename):
    """Serve AI policy documents (PDFs)."""
    from pathlib import Path
    ai_docs_dir = Path(__file__).parent.parent / "ai-docs"
    return send_from_directory(ai_docs_dir, filename)


@app.route('/api')
def api_info():
    """API documentation endpoint - lists all available API routes."""
    api_routes = {
        'info': 'LEAF DSS API v1.0',
        'endpoints': {
            'blocks': {
                'GET /api/blocks': 'Get all blocks as GeoJSON',
                'GET /api/blocks/geojson': 'Get all blocks as GeoJSON (alias)',
                'GET /api/blocks/<block_id>': 'Get block by BLOCK_ID',
                'GET /api/blocks/by-name/<block_name>': 'Get block by name',
            },
            'locations': {
                'GET /api/locations': 'Get hierarchical list of districts, blocks, and GPs',
                'GET /api/districts': 'Get list of all districts with metadata',
                'GET /api/districts/<district>/blocks': 'Get all blocks in a district',
            },
            'gp': {
                'GET /api/gp': 'Get all GPs as GeoJSON',
                'GET /api/gp/geojson': 'Get all GPs as GeoJSON (alias)',
                'GET /api/gp/<gp_id>': 'Get GP by GP_CODE',
                'GET /api/gp/by-name/<gp_name>': 'Get GP by name',
                'GET /api/gp/block/<block_name>': 'Get all GPs in a block',
                'GET /api/gp/locations': 'Get list of GPs grouped by block',
                'GET /api/gp/variables': 'Get GP-level variables',
                'GET /api/gp/statistics': 'Get GP statistics',
                'POST /api/gp/calculate-feasibility': 'Calculate GP feasibility',
            },
            'interventions': {
                'GET /api/interventions': 'List available interventions',
                'GET /api/intervention/<name>/config': 'Get intervention configuration',
            },
            'variables': {
                'GET /api/variables': 'Get all block-level variables',
                'GET /api/variable-groups': 'Get variable groups',
                'GET /api/variable-stats/<variable>': 'Get variable statistics',
            },
            'feasibility': {
                'POST /api/calculate-feasibility': 'Calculate block feasibility',
            },
            'export': {
                'POST /api/export/csv': 'Export data as CSV',
            },
            'config': {
                'GET /api/config': 'Get app configuration',
                'GET /api/levels': 'Get available data levels',
            },
            'health': {
                'GET /health': 'Health check',
            }
        }
    }
    return jsonify(api_routes)


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    # Check if it's an API request
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Endpoint not found', 'path': request.path}), 404
    # For non-API requests, return the main app (SPA style)
    return render_app()


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=5000, debug=True)
