"""Blueprint: production_tool routes (split from app.py)."""
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

production_tool_bp = Blueprint("production_tool", __name__)


@production_tool_bp.route('/api/clusters/<cluster_id>/finalize', methods=['POST'])
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




@production_tool_bp.route('/api/production-tool/clusters')
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




@production_tool_bp.route('/api/production-tool/dashboard/<cluster_id>', methods=['GET', 'POST'])
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
      tool - we only exchange aggregates.
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


