"""Blueprint: gp routes (split from app.py)."""
from flask import Blueprint, render_template, jsonify, request, Response, send_from_directory
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
from clustering import COMMODITIES, DEFAULT_PARAMS
from villages import (
    list_blocks_with_villages,
    villages_for_block,
    villages_geojson,
    aggregate_villages,
    get_clusters,
    get_cluster,
    get_or_regenerate,
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
from shared import (
    get_rag_utils,
    render_app,
    _is_admin_request,
    _cluster_params_from_request,
)

gp_bp = Blueprint("gp", __name__)


@gp_bp.route('/api/gp')
@gp_bp.route('/api/gp/geojson')
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




@gp_bp.route('/api/gp/locations')
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




@gp_bp.route('/api/gp/<gp_id>')
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




@gp_bp.route('/api/gp/by-name/<gp_name>')
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




@gp_bp.route('/api/gp/block/<block_name>')
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




@gp_bp.route('/api/gp/variables')
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




@gp_bp.route('/api/gp/calculate-feasibility', methods=['POST'])
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
        block = data.get('block')  # Optional block filter

        gdf = load_gp_shapefile()
        if gdf is None:
            return jsonify({'error': 'GP data not available'}), 404

        # Filter by block if specified
        if block:
            gdf = gdf[gdf['Block_Name'] == block].copy()

        result = calculate_and_get_geojson(gdf, filters, district=None)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500




@gp_bp.route('/api/gp/statistics')
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


