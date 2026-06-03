"""Blueprint: villages routes (split from app.py)."""
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

villages_bp = Blueprint("villages", __name__)




@villages_bp.route('/api/villages')
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




@villages_bp.route('/api/villages/geojson')
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




@villages_bp.route('/api/villages/aggregate')
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




@villages_bp.route('/api/villages/blocks')
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


