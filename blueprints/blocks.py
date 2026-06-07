"""Blueprint: blocks routes (split from app.py)."""
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

blocks_bp = Blueprint("blocks", __name__)


@blocks_bp.route('/api/blocks')
@blocks_bp.route('/api/blocks/geojson')
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




@blocks_bp.route('/api/blocks/<block_id>')
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




@blocks_bp.route('/api/blocks/by-name/<block_name>')
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




@blocks_bp.route('/api/blocks/<block_name>/shg-summary')
def api_block_shg_summary(block_name):
    """Return SHG aggregates for a block, shaped for the right-side panel.
    ---
    tags:
      - Blocks
    summary: SHG summary for a block
    description: |
      Aggregates the village-level SHG form data (Kobo export) for one block:
      total/mapped/unmapped village counts, GP count, member counts grouped
      into the 6 clustering commodities (Dairy/Goatery/Piggery/Backyard
      Poultry/Duckery/Fishery), plus an "other" group for fodder, feed,
      transport, meat shop, and a raw per-activity breakdown of all 25 form
      questions. Blocks absent from the Kobo export fall back to the village
      master (villages.csv) aggregates — same shape, `source: village_master`,
      with empty `other`/`activities_raw` (no per-activity breakdown there).
      Returns `available: false` only when the block is in neither source.
    parameters:
      - name: block_name
        in: path
        type: string
        required: true
        description: Block name (case-insensitive match).
    responses:
      200:
        description: SHG summary
        schema:
          type: object
          properties:
            district_name: {type: string}
            block_name: {type: string}
            available: {type: boolean}
            source:
              type: string
              description: Present (village_master) when built from the village master fallback.
            villages_total: {type: integer}
            villages_with_gps: {type: integer}
            villages_without_gps: {type: integer}
            gp_count: {type: integer}
            gps: {type: array, items: {type: string}}
            members_total: {type: integer}
            commodities:
              type: object
              properties:
                Dairy: {type: integer}
                Goatery: {type: integer}
                Piggery: {type: integer}
                Backyard_Poultry: {type: integer}
                Duckery: {type: integer}
                Fishery_Activity: {type: integer}
            other:
              type: object
              description: Aggregates for activities outside the 6 cluster commodities.
            activities_raw:
              type: object
              description: Raw totals per Kobo activity key (25 entries).
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        from villages import block_shg_summary
        return jsonify(block_shg_summary(block_name))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Location APIs - Unified location data
# =============================================================================



@blocks_bp.route('/api/statistics')
@blocks_bp.route('/api/blocks/statistics')
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

