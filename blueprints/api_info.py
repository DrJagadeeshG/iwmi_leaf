"""Blueprint: api_info routes (split from app.py)."""
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

api_info_bp = Blueprint("api_info", __name__)


@api_info_bp.route('/api')
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

