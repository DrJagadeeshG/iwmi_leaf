"""Blueprint: locations routes (split from app.py)."""
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

locations_bp = Blueprint("locations", __name__)


@locations_bp.route('/api/locations')
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




@locations_bp.route('/api/districts')
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




@locations_bp.route('/api/districts/geojson')
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




@locations_bp.route('/api/protected-areas/geojson')
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




@locations_bp.route('/api/districts/<district>/blocks')
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


@locations_bp.route('/api/district/names')
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




@locations_bp.route('/api/block/names')
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




@locations_bp.route('/api/gp/names')
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


