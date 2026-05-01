"""
LEAF DSS - Flask Application
Decision Support System for Agricultural Interventions
"""

import os
import json

# Load .env early so DATABASE_URL is available before any module imports it.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass

from flask import Flask, render_template, jsonify, request, Response, send_from_directory
from flask_cors import CORS
from flasgger import Swagger
import pandas as pd

from config import COLORS, FEASIBILITY_COLORS, VARIABLE_GROUPS, MAP_CONFIG
from data_utils import (
    load_shapefile,
    load_metadata,
    load_district_boundaries,
    load_protected_areas,
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

# Swagger / OpenAPI configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: rule.rule.startswith('/api') or rule.rule == '/health',
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "info": {
        "title": "LEAF DSS API",
        "version": "1.0.0",
        "description": (
            "Decision Support System for Agricultural Interventions in Assam, India. "
            "Provides block-level and GP-level geospatial data, feasibility analysis, "
            "and AI-powered recommendations."
        ),
    },
    "tags": [
        {"name": "Blocks", "description": "Block-level geospatial data and lookups"},
        {"name": "Locations", "description": "Hierarchical location data (districts, blocks, GPs)"},
        {"name": "GPs", "description": "Gram Panchayat level data and lookups"},
        {"name": "Interventions", "description": "Agricultural intervention definitions and configurations"},
        {"name": "Variables", "description": "Data variable metadata and statistics"},
        {"name": "Feasibility", "description": "Feasibility score calculation endpoints"},
        {"name": "AI", "description": "AI-powered recommendation engine (RAG-based)"},
        {"name": "Export", "description": "Data export endpoints"},
        {"name": "Config", "description": "Application configuration and metadata"},
        {"name": "Villages", "description": "Village-level point data (ODK / MMUA seed) for cluster generation"},
        {"name": "Clusters", "description": "Per-commodity village clusters: generation, retrieval, CSV edit cycle"},
        {"name": "Infrastructure", "description": "Vet centres, pharmacies, input shops — POI database with nearest-to-cluster query"},
        {"name": "ProductionTool", "description": "Outbound feed of finalised clusters and inbound dashboard data exchange with the external production tool"},
        {"name": "Deprecated", "description": "Deprecated endpoints - use newer alternatives"},
    ],
    "definitions": {
        "Error": {
            "type": "object",
            "properties": {
                "error": {"type": "string", "description": "Error message"}
            }
        },
        "FilterCriteria": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Variable/column name"},
                "min_val": {"type": "number", "description": "Minimum threshold"},
                "max_val": {"type": "number", "description": "Maximum threshold"},
                "weight": {"type": "number", "description": "Weight for scoring (0-1)", "default": 1.0}
            }
        },
        "VariableMetadata": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "label": {"type": "string"},
                "description": {"type": "string"},
                "group": {"type": "string"},
                "data_min": {"type": "number"},
                "data_max": {"type": "number"},
                "data_mean": {"type": "number"}
            }
        },
        "FeasibilityResult": {
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "GeoJSON FeatureCollection with feasibility scores"},
                "statistics": {"type": "object", "description": "Distribution statistics"},
                "filters_applied": {"type": "array", "items": {"$ref": "#/definitions/FilterCriteria"}}
            }
        }
    }
}

Swagger(app, config=swagger_config, template=swagger_template)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'iwmi-leaf-secret-key')


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


@app.route('/update')
@app.route('/update/')
def update_page():
    """Data update page — shows Google Sheet links and refresh controls."""
    from google_sheets import get_status, SHEET_URLS
    return render_template('update.html',
                           status=get_status(),
                           sheet_urls=SHEET_URLS,
                           colors=COLORS)


@app.route('/<district>')
def district_view(district):
    """District level view (shows all blocks in district)."""
    from flask import redirect, url_for
    # Reserved paths — let their own routes handle them
    if district in ('documentation', 'docs', 'api', 'static', 'health', 'update'):
        return redirect(f'/{district}/')
    gdf = load_shapefile()
    valid_districts = gdf['Dist_Name'].dropna().unique().tolist()
    if district not in valid_districts:
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
    """Return all blocks as GeoJSON.
    ---
    tags:
      - Blocks
    summary: Get all blocks as GeoJSON
    description: Returns all blocks as a GeoJSON FeatureCollection with all variable data as feature properties.
    responses:
      200:
        description: GeoJSON FeatureCollection of all blocks
        schema:
          type: object
          properties:
            type:
              type: string
              example: FeatureCollection
            features:
              type: array
              items:
                type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        gdf = load_shapefile()
        geojson = get_blocks_geojson(gdf)
        return jsonify(geojson)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/blocks/<block_id>')
def api_block_detail(block_id):
    """Return single block details by BLOCK_ID.
    ---
    tags:
      - Blocks
    summary: Get block by ID
    description: Returns a single block's data including all variable properties.
    parameters:
      - name: block_id
        in: path
        type: string
        required: true
        description: The BLOCK_ID identifier
    responses:
      200:
        description: Block data object
        schema:
          type: object
      404:
        description: Block not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        block = get_block_by_id(block_id)
        if block is None:
            return jsonify({'error': 'Block not found'}), 404
        return jsonify(block)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/blocks/by-name/<block_name>')
def api_block_by_name(block_name):
    """Return single block details by name.
    ---
    tags:
      - Blocks
    summary: Get block by name
    description: Returns a single block's GeoJSON by its Block_name value.
    parameters:
      - name: block_name
        in: path
        type: string
        required: true
        description: The block name (e.g. "Digboi")
    responses:
      200:
        description: GeoJSON of matching block
        schema:
          type: object
      404:
        description: Block not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return hierarchical list of districts, blocks, and GPs for dropdowns.
    ---
    tags:
      - Locations
    summary: Get hierarchical location data
    description: Returns districts with their blocks and GPs, plus a flat blocks list for backward compatibility.
    responses:
      200:
        description: Location hierarchy
        schema:
          type: object
          properties:
            districts:
              type: array
              items:
                type: object
                properties:
                  name:
                    type: string
                  blocks:
                    type: array
                    items:
                      type: object
                  has_gp_data:
                    type: boolean
            blocks:
              type: array
              items:
                type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return list of all districts with metadata.
    ---
    tags:
      - Locations
    summary: Get all districts
    description: Returns all districts with block counts and GP data availability.
    responses:
      200:
        description: List of districts
        schema:
          type: object
          properties:
            districts:
              type: array
              items:
                type: object
                properties:
                  name:
                    type: string
                  block_count:
                    type: integer
                  has_gp_data:
                    type: boolean
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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


@app.route('/api/districts/geojson')
def api_districts_geojson():
    """Return district boundaries as GeoJSON.
    ---
    tags:
      - Locations
    summary: Get district boundaries as GeoJSON
    description: Returns district boundary polygons as GeoJSON for map display.
    responses:
      200:
        description: GeoJSON FeatureCollection of district boundaries
        schema:
          type: object
      404:
        description: District boundaries not available
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        geojson = load_district_boundaries()
        if geojson is None:
            return jsonify({'error': 'District boundaries not available'}), 404
        return jsonify(geojson)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/protected-areas/geojson')
def api_protected_areas_geojson():
    """Return Protected Areas of India as GeoJSON.
    ---
    tags:
      - Config
    summary: Get protected areas as GeoJSON
    description: Returns Protected Areas of India (national parks, wildlife sanctuaries, etc.) as a GeoJSON FeatureCollection for map overlay display.
    responses:
      200:
        description: GeoJSON FeatureCollection of protected areas
        schema:
          type: object
      404:
        description: Protected areas data not available
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        geojson = load_protected_areas()
        if geojson is None:
            return jsonify({'error': 'Protected areas data not available'}), 404
        return jsonify(geojson)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/districts/<district>/blocks')
def api_district_blocks(district):
    """Return all blocks in a specific district.
    ---
    tags:
      - Locations
    summary: Get blocks in a district
    description: Returns all blocks belonging to the specified district.
    parameters:
      - name: district
        in: path
        type: string
        required: true
        description: District name (e.g. "Tinsukia")
    responses:
      200:
        description: Blocks in district
        schema:
          type: object
          properties:
            district:
              type: string
            blocks:
              type: array
              items:
                type: object
                properties:
                  name:
                    type: string
                  district:
                    type: string
      404:
        description: District not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return list of all district names (deprecated - use /api/districts).
    ---
    tags:
      - Deprecated
    summary: Get district names (deprecated)
    description: "Deprecated: use GET /api/districts instead."
    deprecated: true
    responses:
      200:
        description: List of districts
        schema:
          type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    return api_districts()


@app.route('/api/block/names')
def api_block_names():
    """Return list of all block names (deprecated - use /api/locations).
    ---
    tags:
      - Deprecated
    summary: Get block names (deprecated)
    description: "Deprecated: use GET /api/locations instead."
    deprecated: true
    responses:
      200:
        description: List of block names
        schema:
          type: object
          properties:
            names:
              type: array
              items:
                type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return list of all GP names.
    ---
    tags:
      - GPs
    summary: Get all GP names
    description: Returns a list of all Gram Panchayat names with codes, blocks, and village counts.
    responses:
      200:
        description: List of GP names
        schema:
          type: object
          properties:
            names:
              type: array
              items:
                type: object
                properties:
                  name:
                    type: string
                  code:
                    type: string
                  block:
                    type: string
                  village_count:
                    type: integer
                  district:
                    type: string
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """List available interventions.
    ---
    tags:
      - Interventions
    summary: Get all interventions
    description: Returns the list of available agricultural interventions auto-detected from the CSV configuration.
    responses:
      200:
        description: List of interventions
        schema:
          type: object
          properties:
            interventions:
              type: array
              items:
                type: object
                properties:
                  key:
                    type: string
                  name:
                    type: string
                  description:
                    type: string
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Get all available variables from the shapefile.
    ---
    tags:
      - Variables
    summary: Get all block-level variables
    description: Returns metadata for all numeric variables available in the block-level shapefile, including min/max/mean statistics.
    responses:
      200:
        description: Array of variable metadata
        schema:
          type: array
          items:
            $ref: '#/definitions/VariableMetadata'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Get configuration for a specific intervention.
    ---
    tags:
      - Interventions
    summary: Get intervention configuration
    description: Returns the variable filters and weights configured for the specified intervention.
    parameters:
      - name: name
        in: path
        type: string
        required: true
        description: Intervention key name (e.g. "Organic Farming")
    responses:
      200:
        description: Intervention configuration
        schema:
          type: object
          properties:
            intervention:
              type: string
            name:
              type: string
            description:
              type: string
            variables:
              type: array
              items:
                type: object
      404:
        description: Intervention not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """List available variable groups.
    ---
    tags:
      - Variables
    summary: Get variable groups
    description: Returns the list of variable group categories.
    responses:
      200:
        description: Variable groups
        schema:
          type: object
          properties:
            groups:
              type: array
              items:
                type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        groups = get_variable_groups()
        return jsonify({'groups': groups})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/variable-stats/<variable>')
def api_variable_stats(variable):
    """Get min/max/mean for a variable.
    ---
    tags:
      - Variables
    summary: Get variable statistics
    description: Returns min, max, and mean values for the specified variable column.
    parameters:
      - name: variable
        in: path
        type: string
        required: true
        description: Variable/column name
    responses:
      200:
        description: Variable statistics
        schema:
          type: object
          properties:
            min:
              type: number
            max:
              type: number
            mean:
              type: number
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Calculate feasibility scores with custom filters.
    ---
    tags:
      - Feasibility
    summary: Calculate block-level feasibility
    description: Calculates feasibility scores for all blocks based on the provided variable filters and weights. Returns GeoJSON with scores and distribution statistics.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            intervention:
              type: string
              description: Intervention name (uses default config if no filters provided)
            filters:
              type: array
              description: Custom filter criteria
              items:
                $ref: '#/definitions/FilterCriteria'
            logic:
              type: string
              enum: [AND, OR]
              default: AND
              description: How to combine multiple filters
            district:
              type: string
              description: Optional district ID to filter statistics
    responses:
      200:
        description: Feasibility results
        schema:
          $ref: '#/definitions/FeasibilityResult'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
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
    """Generate AI-powered recommendations based on block data and policy documents.
    ---
    tags:
      - AI
    summary: Get AI recommendation
    description: Uses RAG (Retrieval-Augmented Generation) to generate context-aware recommendations based on block data, feasibility scores, and policy documents.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            block_name:
              type: string
              description: Name of the block
              example: Digboi
            district_name:
              type: string
              description: Name of the district
              example: Tinsukia
            intervention:
              type: string
              description: Selected intervention name
            feasibility_score:
              type: number
              description: Current feasibility score
            metrics:
              type: array
              items:
                type: object
                properties:
                  label:
                    type: string
                  value:
                    type: number
                  in_range:
                    type: boolean
                  min:
                    type: number
                  max:
                    type: number
            filters:
              type: array
              items:
                $ref: '#/definitions/FilterCriteria'
    responses:
      200:
        description: AI recommendation
        schema:
          type: object
          properties:
            recommendation:
              type: string
            sources:
              type: array
              items:
                type: object
      503:
        description: RAG service unavailable
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
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
    """Initialize/rebuild the vector store from PDF documents.
    ---
    tags:
      - AI
    summary: Initialize AI vector store
    description: Rebuilds the RAG vector store by processing PDF policy documents. Required before AI recommendations can be generated.
    responses:
      200:
        description: Initialization result
        schema:
          type: object
          properties:
            success:
              type: boolean
      503:
        description: RAG service unavailable
        schema:
          type: object
          properties:
            success:
              type: boolean
            error:
              type: string
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
            error:
              type: string
    """
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
    """Get distribution statistics for block data.
    ---
    tags:
      - Blocks
    summary: Get block statistics
    description: Returns aggregate statistics for block data including district distribution and column listings.
    responses:
      200:
        description: Block statistics
        schema:
          type: object
          properties:
            total_blocks:
              type: integer
            districts:
              type: object
            district_count:
              type: integer
            columns:
              type: array
              items:
                type: string
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Export filtered data as CSV.
    ---
    tags:
      - Export
    summary: Export data as CSV
    description: Exports block data as a CSV file, optionally with feasibility scores calculated from the provided filters.
    produces:
      - text/csv
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            intervention:
              type: string
              description: Intervention name for default filters
            filters:
              type: array
              items:
                $ref: '#/definitions/FilterCriteria'
            logic:
              type: string
              enum: [AND, OR]
              default: AND
    responses:
      200:
        description: CSV file download
        schema:
          type: file
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Get app configuration (colors, thresholds, etc.).
    ---
    tags:
      - Config
    summary: Get application configuration
    description: Returns color schemes, feasibility color thresholds, and map configuration.
    responses:
      200:
        description: Application configuration
        schema:
          type: object
          properties:
            colors:
              type: object
            feasibility_colors:
              type: object
            map_config:
              type: object
    """
    return jsonify({
        'colors': COLORS,
        'feasibility_colors': FEASIBILITY_COLORS,
        'map_config': MAP_CONFIG,
    })


@app.route('/api/config/refresh', methods=['POST'])
def api_config_refresh():
    """Force-refresh data from Google Sheets.
    ---
    tags:
      - Config
    summary: Refresh Google Sheets data
    description: Forces a re-fetch of all data from published Google Sheets, bypassing the TTL cache.
    responses:
      200:
        description: Refresh results
        schema:
          type: object
          properties:
            refreshed:
              type: object
              description: Map of sheet key to success boolean
            status:
              type: object
              description: Current cache status after refresh
    """
    from google_sheets import refresh, get_status
    results = refresh()
    return jsonify({
        'refreshed': results,
        'status': get_status(),
    })


@app.route('/api/config/sheets-status')
def api_sheets_status():
    """Get Google Sheets cache status.
    ---
    tags:
      - Config
    summary: Get Google Sheets sync status
    description: Returns the current cache status for all Google Sheet data sources.
    responses:
      200:
        description: Cache status for each sheet
        schema:
          type: object
    """
    from google_sheets import get_status
    return jsonify(get_status())


# =============================================================================
# GP (Gram Panchayat) Level APIs
# =============================================================================

@app.route('/api/gp')
@app.route('/api/gp/geojson')
def api_gp_geojson():
    """Return all GPs as GeoJSON.
    ---
    tags:
      - GPs
    summary: Get all GPs as GeoJSON
    description: Returns all Gram Panchayats as a GeoJSON FeatureCollection with variable data as properties.
    responses:
      200:
        description: GeoJSON FeatureCollection of GPs
        schema:
          type: object
      404:
        description: GP data not available
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return list of GPs grouped by block for dropdowns.
    ---
    tags:
      - GPs
    summary: Get GP locations grouped by block
    description: Returns GP locations as both a flat list and grouped by block for dropdown population.
    responses:
      200:
        description: GP locations
        schema:
          type: object
          properties:
            gps:
              type: array
              items:
                type: object
            by_block:
              type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return single GP details by GP_CODE.
    ---
    tags:
      - GPs
    summary: Get GP by ID
    description: Returns a single Gram Panchayat's data by its GP_CODE identifier.
    parameters:
      - name: gp_id
        in: path
        type: string
        required: true
        description: The GP_CODE identifier
    responses:
      200:
        description: GP data object
        schema:
          type: object
      404:
        description: GP not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        gp = get_gp_by_id(gp_id)
        if gp is None:
            return jsonify({'error': 'GP not found'}), 404
        return jsonify(gp)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gp/by-name/<gp_name>')
def api_gp_by_name(gp_name):
    """Return single GP details by name.
    ---
    tags:
      - GPs
    summary: Get GP by name
    description: Returns a single Gram Panchayat's GeoJSON by its GP_NAME.
    parameters:
      - name: gp_name
        in: path
        type: string
        required: true
        description: The GP name
    responses:
      200:
        description: GeoJSON of matching GP
        schema:
          type: object
      404:
        description: GP not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return all GPs in a specific block.
    ---
    tags:
      - GPs
    summary: Get GPs by block
    description: Returns all Gram Panchayats belonging to the specified block.
    parameters:
      - name: block_name
        in: path
        type: string
        required: true
        description: Block name (e.g. "Digboi")
    responses:
      200:
        description: GPs in block
        schema:
          type: object
          properties:
            block:
              type: string
            district:
              type: string
            gps:
              type: array
              items:
                type: object
                properties:
                  name:
                    type: string
                  code:
                    type: string
                  village_count:
                    type: integer
      404:
        description: No GPs found in block
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Get all available GP-level variables.
    ---
    tags:
      - GPs
    summary: Get GP-level variables
    description: Returns metadata for all numeric variables available in the GP-level shapefile.
    responses:
      200:
        description: Array of GP variable metadata
        schema:
          type: array
          items:
            $ref: '#/definitions/VariableMetadata'
      404:
        description: GP data not available
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Calculate feasibility scores for GP level.
    ---
    tags:
      - Feasibility
    summary: Calculate GP-level feasibility
    description: Calculates feasibility scores for Gram Panchayats based on the provided filters. Optionally filter by block.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            filters:
              type: array
              items:
                $ref: '#/definitions/FilterCriteria'
            logic:
              type: string
              enum: [AND, OR]
              default: AND
            block:
              type: string
              description: Optional block name to filter GPs
    responses:
      200:
        description: GP feasibility results
        schema:
          $ref: '#/definitions/FeasibilityResult'
      404:
        description: GP data not available
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Get statistics for GP data.
    ---
    tags:
      - GPs
    summary: Get GP statistics
    description: Returns aggregate statistics for GP data including block distribution.
    responses:
      200:
        description: GP statistics
        schema:
          type: object
          properties:
            total_gps:
              type: integer
            district:
              type: string
            blocks:
              type: object
            columns:
              type: array
              items:
                type: string
      404:
        description: GP data not available
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
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
    """Return available data levels and districts with GP support.
    ---
    tags:
      - Config
    summary: Get available data levels
    description: Returns the available data hierarchy levels (block, GP) and which districts support GP-level data.
    responses:
      200:
        description: Data levels
        schema:
          type: object
          properties:
            levels:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
                  available:
                    type: boolean
            gp_districts:
              type: array
              items:
                type: string
    """
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
    """Health check endpoint.
    ---
    tags:
      - Config
    summary: Health check
    description: Returns service health status.
    responses:
      200:
        description: Service is healthy
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
    """
    return jsonify({'status': 'healthy'})


@app.route('/ai-docs/<path:filename>')
def serve_ai_docs(filename):
    """Serve AI policy documents (PDFs)."""
    from pathlib import Path
    ai_docs_dir = Path(__file__).parent.parent / "ai-docs"
    return send_from_directory(ai_docs_dir, filename)


@app.route('/documentation/')
@app.route('/documentation/<path:filename>')
def serve_documentation(filename='index.html'):
    """Serve the MkDocs documentation site."""
    from pathlib import Path
    site_dir = Path(__file__).parent / "site"
    if not site_dir.exists():
        return jsonify({'error': 'Documentation not built', 'site_dir': str(site_dir)}), 404
    # MkDocs uses directory-style URLs (e.g. quickstart/ → quickstart/index.html)
    if filename.endswith('/') or '.' not in filename.split('/')[-1]:
        candidate = site_dir / filename / 'index.html'
        if candidate.exists():
            filename = filename.rstrip('/') + '/index.html'
    return send_from_directory(site_dir, filename)


# =============================================================================
# Villages & Clusters APIs
# =============================================================================

from clustering import COMMODITIES, DEFAULT_PARAMS
from villages import (
    list_blocks_with_villages,
    villages_for_block,
    villages_geojson,
    aggregate_villages,
    get_clusters,
    get_cluster,
    regenerate_clusters,
    replace_clusters_from_records,
    clusters_to_csv,
    csv_text_to_records,
    set_cluster_finalized,
    set_cluster_dashboard,
)
from infrastructure import (
    list_infrastructure,
    import_infrastructure_csv,
    nearest_to_point,
)


def _cluster_params_from_request():
    """Pull tunable clustering params from query string or JSON body, applying defaults."""
    src = {}
    src.update({k: request.args.get(k) for k in DEFAULT_PARAMS if request.args.get(k) is not None})
    if request.is_json:
        body = request.get_json(silent=True) or {}
        for k in DEFAULT_PARAMS:
            if k in body and body[k] is not None:
                src[k] = body[k]
    out = {}
    for k, default in DEFAULT_PARAMS.items():
        if k in src:
            out[k] = float(src[k]) if isinstance(default, float) else int(src[k])
    return out


@app.route('/api/villages')
def api_villages():
    """List villages with commodity member counts.
    ---
    tags:
      - Villages
    summary: List villages
    description: |
      Returns village-level rows (district, block, GP, name, lat/long, and member
      counts for each commodity) seeded from the MMUA `Random_pointshapefile` sheet.
      Filter by `block` to scope to one block (the level at which clustering runs).
    parameters:
      - name: block
        in: query
        type: string
        required: false
        description: Filter to villages within a single block (case-sensitive match on `block_name`).
    responses:
      200:
        description: Array of village records
        schema:
          type: array
          items:
            type: object
            properties:
              district_name: {type: string}
              block_name: {type: string}
              gp_name: {type: string}
              vill_name: {type: string}
              lat: {type: number}
              long: {type: number}
              Dairy: {type: integer}
              Goatery: {type: integer}
              Piggery: {type: integer}
              Backyard_Poultry: {type: integer}
              Duckery: {type: integer}
              Fishery_Activity: {type: integer}
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        block = request.args.get('block')
        df = villages_for_block(block) if block else __import__('villages').load_villages()
        return jsonify(df.to_dict(orient='records'))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/villages/geojson')
def api_villages_geojson():
    """Return villages as a GeoJSON FeatureCollection of points.
    ---
    tags:
      - Villages
    summary: Villages as GeoJSON points
    description: Each feature is a Point with all village properties (commodity member counts, GP, block, district).
    parameters:
      - name: block
        in: query
        type: string
        required: false
        description: Filter to villages within a single block.
    responses:
      200:
        description: GeoJSON FeatureCollection
        schema:
          type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        block = request.args.get('block')
        return jsonify(villages_geojson(block_name=block))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/villages/aggregate')
def api_villages_aggregate():
    """Aggregated village/member counts for state- or district-scale map overlays.
    ---
    tags:
      - Villages
    summary: Aggregated village counts
    description: |
      Drives the state and district map levels per the IWMI requirements call
      (2026-04-23): rendering 25k points at state scale is meaningless, so
      the map shows aggregated numbers per district at state scale and per
      block at district scale. Village points are reserved for block scale.
      Each row sums villages and members per commodity within the group.
    parameters:
      - name: level
        in: query
        type: string
        required: true
        enum: [district, block]
        description: Aggregation grain
      - name: district
        in: query
        type: string
        required: false
        description: When level=block, restrict to one district
    responses:
      200:
        description: Array of aggregated rows
        schema:
          type: array
          items:
            type: object
            properties:
              district_name: {type: string}
              block_name: {type: string, description: Present only when level=block}
              village_count: {type: integer}
              Dairy: {type: integer}
              Goatery: {type: integer}
              Piggery: {type: integer}
              Backyard_Poultry: {type: integer}
              Duckery: {type: integer}
              Fishery_Activity: {type: integer}
      400:
        description: Bad request
        schema: {$ref: '#/definitions/Error'}
    """
    level = request.args.get('level')
    if level not in ('district', 'block'):
        return jsonify({'error': "Query parameter `level` must be 'district' or 'block'"}), 400
    try:
        return jsonify(aggregate_villages(level=level, district=request.args.get('district')))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/villages/blocks')
def api_villages_blocks():
    """List blocks that have village-level data available.
    ---
    tags:
      - Villages
    summary: Blocks with village data
    description: Returns one record per (district, block) with village count, useful for the block-scale map drill-down.
    responses:
      200:
        description: Array of block summaries
        schema:
          type: array
          items:
            type: object
            properties:
              district_name: {type: string}
              block_name: {type: string}
              village_count: {type: integer}
    """
    try:
        return jsonify(list_blocks_with_villages())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clusters/params')
def api_cluster_params():
    """Get the default clustering parameters.
    ---
    tags:
      - Clusters
    summary: Default clustering parameters
    description: |
      Returns the tunable parameters used by the clustering engine. All four can be
      overridden per-request on `/api/clusters` (POST) and `/api/clusters/regenerate`.
      The 30/50 member range and 5 km radius reflect government criteria (per IWMI
      requirements call, 2026-04-23) and may be adjusted before final freeze.
    responses:
      200:
        description: Parameter map
        schema:
          type: object
          properties:
            min_members_per_village: {type: integer}
            min_cluster_members: {type: integer}
            max_cluster_members: {type: integer}
            min_villages_per_cluster: {type: integer}
            max_villages_per_cluster: {type: integer}
            max_radius_km: {type: number}
            commodities:
              type: array
              items: {type: string}
    """
    return jsonify({**DEFAULT_PARAMS, "commodities": COMMODITIES})


@app.route('/api/clusters')
def api_clusters_list():
    """List stored clusters, optionally filtered.
    ---
    tags:
      - Clusters
    summary: List clusters
    description: |
      Returns clusters previously generated and stored on the server. Use the
      filters to scope to a block, district, or commodity. If no clusters exist
      yet, call `POST /api/clusters/regenerate` to run the algorithm.
    parameters:
      - name: block
        in: query
        type: string
        required: false
        description: Filter by block_name
      - name: district
        in: query
        type: string
        required: false
        description: Filter by district_name
      - name: commodity
        in: query
        type: string
        required: false
        enum: [Dairy, Goatery, Piggery, Backyard_Poultry, Duckery, Fishery_Activity]
    responses:
      200:
        description: Array of cluster records
    """
    try:
        clusters = get_clusters(
            block_name=request.args.get('block'),
            commodity=request.args.get('commodity'),
            district_name=request.args.get('district'),
        )
        return jsonify(clusters)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clusters/<cluster_id>')
def api_cluster_detail(cluster_id):
    """Get a single cluster by its ID.
    ---
    tags:
      - Clusters
    summary: Get cluster by ID
    parameters:
      - name: cluster_id
        in: path
        type: string
        required: true
    responses:
      200: {description: Cluster record}
      404:
        description: Not found
        schema: {$ref: '#/definitions/Error'}
    """
    c = get_cluster(cluster_id)
    if c is None:
        return jsonify({'error': f'Cluster {cluster_id} not found'}), 404
    return jsonify(c)


@app.route('/api/clusters/<cluster_id>/report')
def api_cluster_report(cluster_id):
    """Cluster dashboard / report card.
    ---
    tags:
      - Clusters
    summary: Cluster report card
    description: |
      Returns the cluster's villages, total members, max span, plus the existing
      block-level LEAF variables (soil, water, climate, infrastructure, people,
      livestock, land/agri) for the parent block. Mirrors the mock on slide 7
      of the LEAF DSS Clustering Workflow deck.
    parameters:
      - name: cluster_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Cluster + block-level context
        schema:
          type: object
          properties:
            cluster: {type: object}
            block: {type: object, description: Properties from the parent block (LEAF variables)}
      404:
        description: Cluster or block not found
        schema: {$ref: '#/definitions/Error'}
    """
    c = get_cluster(cluster_id)
    if c is None:
        return jsonify({'error': f'Cluster {cluster_id} not found'}), 404
    try:
        gdf = load_shapefile()
        block_match = gdf[gdf['Block_name'].astype(str).str.upper() == str(c.get('block_name', '')).upper()]
        block_props = {}
        if not block_match.empty:
            row = block_match.iloc[0].drop(labels=['geometry'], errors='ignore').to_dict()
            block_props = {k: (None if pd.isna(v) else v) for k, v in row.items()}
        return jsonify({'cluster': c, 'block': block_props})
    except Exception as e:
        return jsonify({'cluster': c, 'block': {}, 'warning': str(e)}), 200


@app.route('/api/clusters/regenerate', methods=['POST'])
def api_clusters_regenerate():
    """Run the clustering algorithm and replace stored clusters in scope.
    ---
    tags:
      - Clusters
    summary: Regenerate clusters
    description: |
      Runs the greedy spatial clustering algorithm on the village seed data and
      stores the resulting clusters. Scope precedence: (block + commodity) >
      (block) > (all blocks, all commodities). Tunable parameters can be passed
      in the body and override defaults from `/api/clusters/params`.
    parameters:
      - in: body
        name: body
        required: false
        schema:
          type: object
          properties:
            block:
              type: string
              description: Restrict to one block (recommended)
            commodity:
              type: string
              enum: [Dairy, Goatery, Piggery, Backyard_Poultry, Duckery, Fishery_Activity]
            min_members_per_village: {type: integer}
            min_cluster_members: {type: integer}
            max_cluster_members: {type: integer}
            min_villages_per_cluster: {type: integer}
            max_villages_per_cluster: {type: integer}
            max_radius_km: {type: number}
    responses:
      200:
        description: Newly generated clusters
        schema:
          type: object
          properties:
            count: {type: integer}
            clusters:
              type: array
              items: {type: object}
      500:
        description: Server error
        schema: {$ref: '#/definitions/Error'}
    """
    try:
        body = request.get_json(silent=True) or {}
        block = body.get('block')
        commodity = body.get('commodity')
        params = _cluster_params_from_request()
        clusters = regenerate_clusters(block_name=block, commodity=commodity, params=params)
        return jsonify({'count': len(clusters), 'clusters': clusters})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clusters/export.csv')
def api_clusters_export_csv():
    """Export stored clusters as a row-per-village CSV.
    ---
    tags:
      - Clusters
    summary: Export clusters CSV
    description: |
      Produces a CSV with one row per (cluster, village). Editors can change
      villages, member counts, or fill in `pashu_sakhi` / `block_coordinator`,
      then re-upload via `POST /api/clusters/import` to update the stored
      clusters. Same edit-via-CSV pattern as the existing LEAF data update flow.
    parameters:
      - name: block
        in: query
        type: string
        required: false
      - name: district
        in: query
        type: string
        required: false
      - name: commodity
        in: query
        type: string
        required: false
        enum: [Dairy, Goatery, Piggery, Backyard_Poultry, Duckery, Fishery_Activity]
    responses:
      200:
        description: CSV file
        schema: {type: string}
    """
    try:
        clusters = get_clusters(
            block_name=request.args.get('block'),
            commodity=request.args.get('commodity'),
            district_name=request.args.get('district'),
        )
        csv_text = clusters_to_csv(clusters)
        scope = request.args.get('block') or request.args.get('district') or 'all'
        return Response(
            csv_text,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=clusters_{scope}.csv'},
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clusters/import', methods=['POST'])
def api_clusters_import():
    """Replace stored clusters in scope from an uploaded CSV.
    ---
    tags:
      - Clusters
    summary: Import clusters CSV
    description: |
      Accepts the same row-per-village CSV format produced by
      `/api/clusters/export.csv`. Required scope: `block` (and optionally
      `commodity`). All existing clusters within scope are replaced by the
      uploaded rows; derived fields (total_members, max_span_km, centroid) are
      recomputed. Re-upload as many times as needed.
    consumes:
      - multipart/form-data
      - text/csv
    parameters:
      - in: formData
        name: file
        type: file
        required: false
        description: Multipart CSV file. Alternatively POST raw CSV as the request body.
      - in: query
        name: block
        type: string
        required: true
      - in: query
        name: commodity
        type: string
        required: false
        enum: [Dairy, Goatery, Piggery, Backyard_Poultry, Duckery, Fishery_Activity]
    responses:
      200:
        description: Import summary
        schema:
          type: object
          properties:
            imported: {type: integer, description: Number of clusters stored}
      400:
        description: Bad request
        schema: {$ref: '#/definitions/Error'}
    """
    try:
        block = request.args.get('block')
        commodity = request.args.get('commodity')
        if not block:
            return jsonify({'error': 'Query parameter `block` is required'}), 400

        csv_text = ''
        if 'file' in request.files:
            csv_text = request.files['file'].read().decode('utf-8-sig')
        else:
            csv_text = request.get_data(as_text=True)
        if not csv_text.strip():
            return jsonify({'error': 'No CSV content received'}), 400

        records = csv_text_to_records(csv_text)
        n = replace_clusters_from_records(records, scope={'block_name': block, 'commodity': commodity})
        return jsonify({'imported': n})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Infrastructure POI APIs
# =============================================================================

@app.route('/api/infrastructure')
def api_infrastructure_list():
    """List infrastructure POIs (vet centres, pharmacies, input shops, etc.).
    ---
    tags:
      - Infrastructure
    summary: List POIs
    description: |
      Returns infrastructure points-of-interest ingested via
      `POST /api/infrastructure/import`. Filterable by type, district, block.
    parameters:
      - name: type
        in: query
        type: string
        required: false
        description: Filter by POI type (case-insensitive), e.g. 'vet_centre', 'pharmacy', 'input_shop'.
      - name: block
        in: query
        type: string
        required: false
      - name: district
        in: query
        type: string
        required: false
    responses:
      200:
        description: Array of POI records
        schema:
          type: array
          items:
            type: object
            properties:
              type: {type: string}
              name: {type: string}
              lat: {type: number}
              long: {type: number}
              district_name: {type: string}
              block_name: {type: string}
              gp_name: {type: string}
              vill_name: {type: string}
    """
    try:
        return jsonify(list_infrastructure(
            type_=request.args.get('type'),
            block=request.args.get('block'),
            district=request.args.get('district'),
        ))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/infrastructure/import', methods=['POST'])
def api_infrastructure_import():
    """Replace the infrastructure POI dataset from an uploaded CSV.
    ---
    tags:
      - Infrastructure
    summary: Import POIs CSV
    description: |
      Replaces the entire infrastructure dataset. Required columns:
      `type, name, lat, long`. Optional: `district_name, block_name, gp_name,
      vill_name`. Same backend-CSV-upload pattern as the existing LEAF data
      update flow.
    consumes:
      - multipart/form-data
      - text/csv
    parameters:
      - in: formData
        name: file
        type: file
        required: false
        description: Multipart CSV file. Alternatively POST raw CSV as the request body.
    responses:
      200:
        description: Import summary
        schema:
          type: object
          properties:
            imported: {type: integer}
      400:
        description: Bad request (missing required columns or empty body)
        schema: {$ref: '#/definitions/Error'}
    """
    try:
        csv_text = ''
        if 'file' in request.files:
            csv_text = request.files['file'].read().decode('utf-8-sig')
        else:
            csv_text = request.get_data(as_text=True)
        if not csv_text.strip():
            return jsonify({'error': 'No CSV content received'}), 400
        n = import_infrastructure_csv(csv_text)
        return jsonify({'imported': n})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/infrastructure/nearest')
def api_infrastructure_nearest():
    """Nearest infrastructure POIs to a cluster centroid or arbitrary point.
    ---
    tags:
      - Infrastructure
    summary: Nearest POIs
    description: |
      Provide either `cluster_id` (uses the cluster centroid) or `lat`+`long`.
      Returns up to `n` nearest POIs with `distance_km` attached, optionally
      filtered by `type` and capped at `max_km`.
    parameters:
      - name: cluster_id
        in: query
        type: string
        required: false
      - name: lat
        in: query
        type: number
        required: false
      - name: long
        in: query
        type: number
        required: false
      - name: type
        in: query
        type: string
        required: false
      - name: n
        in: query
        type: integer
        required: false
        default: 5
      - name: max_km
        in: query
        type: number
        required: false
    responses:
      200:
        description: Array of POIs sorted by distance
        schema:
          type: array
          items: {type: object}
      400:
        description: Bad request
        schema: {$ref: '#/definitions/Error'}
      404:
        description: Cluster not found
        schema: {$ref: '#/definitions/Error'}
    """
    cluster_id = request.args.get('cluster_id')
    if cluster_id:
        c = get_cluster(cluster_id)
        if c is None:
            return jsonify({'error': f'Cluster {cluster_id} not found'}), 404
        lat = float(c['centroid_lat'])
        lon = float(c['centroid_lon'])
    else:
        lat_raw = request.args.get('lat')
        lon_raw = request.args.get('long')
        if lat_raw is None or lon_raw is None:
            return jsonify({'error': 'Provide cluster_id or both lat and long'}), 400
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            return jsonify({'error': 'lat/long must be numbers'}), 400

    try:
        n = int(request.args.get('n', 5))
        max_km = request.args.get('max_km')
        max_km = float(max_km) if max_km is not None else None
        return jsonify(nearest_to_point(lat, lon, type_=request.args.get('type'), n=n, max_km=max_km))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Production Tool API surface
# =============================================================================

@app.route('/api/clusters/<cluster_id>/finalize', methods=['POST'])
def api_cluster_finalize(cluster_id):
    """Mark a cluster as finalised (or unfinalize it).
    ---
    tags:
      - ProductionTool
    summary: Finalize cluster
    description: |
      Once a cluster has been reviewed and edited via the CSV cycle, flipping
      `finalized=true` includes it in the outbound feed at
      `/api/production-tool/clusters`. Pass `{"finalized": false}` to revert.
    parameters:
      - name: cluster_id
        in: path
        type: string
        required: true
      - in: body
        name: body
        required: false
        schema:
          type: object
          properties:
            finalized: {type: boolean, default: true}
    responses:
      200:
        description: Updated cluster record
        schema: {type: object}
      404:
        description: Cluster not found
        schema: {$ref: '#/definitions/Error'}
    """
    body = request.get_json(silent=True) or {}
    finalized = bool(body.get('finalized', True))
    rec = set_cluster_finalized(cluster_id, finalized)
    if rec is None:
        return jsonify({'error': f'Cluster {cluster_id} not found'}), 404
    return jsonify(rec)


@app.route('/api/production-tool/clusters')
def api_production_tool_clusters():
    """Outbound feed of finalised clusters for the external production tool.
    ---
    tags:
      - ProductionTool
    summary: Outbound clusters feed
    description: |
      Read-only. Returns clusters with `finalized=true`, scoped to the requested
      district / block / commodity. This is the contract the external
      production tool consumes once a cluster is locked down.
    parameters:
      - name: block
        in: query
        type: string
        required: false
      - name: district
        in: query
        type: string
        required: false
      - name: commodity
        in: query
        type: string
        required: false
        enum: [Dairy, Goatery, Piggery, Backyard_Poultry, Duckery, Fishery_Activity]
    responses:
      200:
        description: Array of finalised clusters
        schema:
          type: array
          items: {type: object}
    """
    clusters = get_clusters(
        block_name=request.args.get('block'),
        commodity=request.args.get('commodity'),
        district_name=request.args.get('district'),
    )
    return jsonify([c for c in clusters if c.get('finalized')])


@app.route('/api/production-tool/dashboard/<cluster_id>', methods=['GET', 'POST'])
def api_production_tool_dashboard(cluster_id):
    """Inbound aggregated dashboard data from the production tool, per cluster.
    ---
    tags:
      - ProductionTool
    summary: Cluster production dashboard
    description: |
      The external production tool POSTs aggregate output (e.g. duckery cluster:
      eggs produced, meat output) keyed by cluster_id; we store the JSON as-is
      and surface it on the cluster report card. GET returns the last stored
      payload. Authentication and per-user filtering live in the production
      tool — we only exchange aggregates.
    parameters:
      - name: cluster_id
        in: path
        type: string
        required: true
      - in: body
        name: body
        required: false
        schema:
          type: object
          description: Arbitrary JSON dashboard payload (POST only)
    responses:
      200:
        description: Stored payload (or empty object if not yet posted)
        schema: {type: object}
      404:
        description: Cluster not found
        schema: {$ref: '#/definitions/Error'}
    """
    if request.method == 'POST':
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({'error': 'JSON body required'}), 400
        rec = set_cluster_dashboard(cluster_id, payload)
        if rec is None:
            return jsonify({'error': f'Cluster {cluster_id} not found'}), 404
        return jsonify(rec.get('dashboard', {}))

    rec = get_cluster(cluster_id)
    if rec is None:
        return jsonify({'error': f'Cluster {cluster_id} not found'}), 404
    return jsonify(rec.get('dashboard') or {})


@app.route('/api')
def api_info():
    """API documentation endpoint - lists all available API routes.
    ---
    tags:
      - Config
    summary: API information
    description: Returns a structured list of all available API endpoints and their descriptions.
    responses:
      200:
        description: API endpoint listing
        schema:
          type: object
          properties:
            info:
              type: string
            endpoints:
              type: object
    """
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
                'GET /api/protected-areas/geojson': 'Get protected areas as GeoJSON',
            },
            'villages': {
                'GET /api/villages': 'List villages (optionally filtered by block)',
                'GET /api/villages/geojson': 'Villages as GeoJSON points',
                'GET /api/villages/aggregate': 'Aggregated counts by district or block (state/district map levels)',
                'GET /api/villages/blocks': 'Blocks with village data available',
            },
            'clusters': {
                'GET /api/clusters/params': 'Default clustering parameters',
                'GET /api/clusters': 'List stored clusters (filter by block/district/commodity)',
                'GET /api/clusters/<cluster_id>': 'Get a cluster by ID',
                'GET /api/clusters/<cluster_id>/report': 'Cluster report card with block-level LEAF variables',
                'POST /api/clusters/regenerate': 'Run clustering algorithm and replace stored clusters in scope',
                'GET /api/clusters/export.csv': 'Export clusters as row-per-village CSV',
                'POST /api/clusters/import': 'Replace stored clusters in scope from uploaded CSV',
                'POST /api/clusters/<cluster_id>/finalize': 'Mark a cluster as finalised',
            },
            'infrastructure': {
                'GET /api/infrastructure': 'List POIs (filter by type/block/district)',
                'POST /api/infrastructure/import': 'Replace POI dataset from CSV',
                'GET /api/infrastructure/nearest': 'Nearest POIs to cluster centroid or arbitrary point',
            },
            'production_tool': {
                'GET /api/production-tool/clusters': 'Outbound feed of finalised clusters',
                'GET /api/production-tool/dashboard/<cluster_id>': 'Get stored dashboard payload',
                'POST /api/production-tool/dashboard/<cluster_id>': 'Receive aggregated dashboard data per cluster',
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
