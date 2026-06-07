"""Blueprint: clusters routes (split from app.py)."""
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

clusters_bp = Blueprint("clusters", __name__)


def _regenerate_clusters(*args, **kwargs):
    """Resolve regenerate_clusters through the app module so tests that
    monkeypatch ``app.regenerate_clusters`` (and the original app.py namespace
    behaviour) still take effect after the blueprint split. Deferred import
    avoids a circular import at module load (app imports this blueprint)."""
    import app as _app
    fn = getattr(_app, 'regenerate_clusters', regenerate_clusters)
    return fn(*args, **kwargs)


@clusters_bp.route('/api/clusters/params')
def api_cluster_params():
    """Get the default clustering parameters.
    ---
    tags:
      - Clusters
    summary: Default clustering parameters
    description: |
      Returns the tunable parameters used by the clustering engine. All can be
      overridden per-request on `/api/clusters` (POST) and `/api/clusters/regenerate`.
      The 30/150 member range and 5 km radius reflect government criteria (per IWMI
      requirements call, 2026-04-23) and may be adjusted before final freeze.
      `emit_provisional` surfaces below-floor village groups as provisional
      clusters (flagged, not fundable) instead of dropping them. `rebalance`
      (default false) lets a provisional group become fundable by borrowing a
      village from an adjacent fundable cluster when every cap still holds and
      the donor stays valid; it is OFF by default and changes output broadly, so
      enable it deliberately.
    responses:
      200:
        description: Parameter map
        schema:
          type: object
          properties:
            min_members_per_village: {type: integer}
            min_cluster_members: {type: integer}
            max_cluster_members: {type: integer}
            max_radius_km: {type: number}
            emit_provisional: {type: boolean}
            provisional_min_members: {type: integer}
            rebalance: {type: boolean}
            commodities:
              type: array
              items: {type: string}
    """
    return jsonify({**DEFAULT_PARAMS, "commodities": COMMODITIES})




@clusters_bp.route('/api/clusters')
def api_clusters_list():
    """List stored clusters, optionally filtered.
    ---
    tags:
      - Clusters
    summary: List clusters
    description: |
      Returns stored clusters, scoped by `block`, `district`, or `commodity`.

      **Smart auto-refresh:** when a `block` is given, each in-scope
      (block, commodity) is transparently regenerated *only* when it is stale —
      i.e. the algorithm version, params, or underlying village data changed
      since it was last generated — **and** the scope is not locked (no
      finalized clusters and no uploaded-CSV edits). Fresh or human-owned scopes
      are served as-is, so reloads never wipe edits and unchanged scopes aren't
      needlessly rebuilt. No explicit `POST /api/clusters/regenerate` is needed
      for routine viewing.

      Each record carries three identifiers: `cluster_id` (stable internal
      UUID key), `cluster_num`/`cluster_label` (within-tier sequence, `1`/`P1`)
      and `cluster_code` - the human-readable unique code shown in the UI:
      hyphen-separated first two letters of district + block + commodity
      (intervention type) followed by the sequence number (e.g. `MO-BH-GO-01`;
      provisional `MO-BH-GO-P01`). The code is derived at read time, so CSV
      splits/merges renumber on the next read.
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
        block = request.args.get('block')
        commodity = request.args.get('commodity')
        district = request.args.get('district')
        params = _cluster_params_from_request()
        if block:
            # Smart-refresh: regenerate stale, unlocked scopes only (see
            # villages.get_or_regenerate). Skipped without a block to avoid a
            # full-corpus run on an unscoped read.
            clusters = get_or_regenerate(
                block_name=block,
                commodity=commodity,
                district_name=district,
                params=params or None,
            )
        else:
            clusters = get_clusters(
                block_name=block,
                commodity=commodity,
                district_name=district,
            )
        return jsonify(clusters)
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@clusters_bp.route('/api/clusters/<cluster_id>')
def api_cluster_detail(cluster_id):
    """Get a single cluster by its ID.
    ---
    tags:
      - Clusters
    summary: Get cluster by ID
    description: |
      Returns one cluster record by its internal `cluster_id`. The record also
      carries the derived `cluster_num`/`cluster_label` (within-tier sequence)
      and `cluster_code` (human-readable unique code, e.g. `MO-BH-GO-01`).
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




@clusters_bp.route('/api/clusters/<cluster_id>/report')
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




@clusters_bp.route('/api/clusters/regenerate', methods=['POST'])
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

      **Admin-only.** Requires either `?admin=1` query param or `X-Admin: 1`
      header. Regenerate wipes any user edits/CSV uploads in scope, so it is
      gated to avoid accidental clicks from regular users (per Faiz, 2026-05-09).
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
      403:
        description: Admin flag missing
        schema: {$ref: '#/definitions/Error'}
      500:
        description: Server error
        schema: {$ref: '#/definitions/Error'}
    """
    if not _is_admin_request():
        return jsonify({'error': 'Admin-only endpoint. Pass ?admin=1 or X-Admin: 1.'}), 403
    try:
        body = request.get_json(silent=True) or {}
        block = body.get('block')
        commodity = body.get('commodity')
        params = _cluster_params_from_request()
        clusters = _regenerate_clusters(block_name=block, commodity=commodity, params=params)
        return jsonify({'count': len(clusters), 'clusters': clusters})
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@clusters_bp.route('/api/clusters/export.csv')
def api_clusters_export_csv():
    """Export stored clusters as a row-per-village CSV.
    ---
    tags:
      - Clusters
    summary: Export clusters CSV
    description: |
      Produces a CSV with one row per (cluster, village). Columns: cluster_code,
      cluster_num, cluster_id, commodity, district_name, block_name, gp_name,
      vill_name, lat, long, members, pashu_sakhi, block_coordinator.
      `cluster_code` is the human-readable unique code (hyphen-separated first
      two letters of district + block + commodity, then the sequence number,
      e.g. `MO-BH-GO-01`; provisional tier carries a `P`, e.g. `MO-BH-GO-P01`).
      It is display-only and
      ignored on import - `cluster_id` remains the join key. Editors can change
      villages, member counts, fill in `pashu_sakhi` / `block_coordinator`, or
      append a row for a brand-new village discovered in the field by supplying
      its lat/long inline. Re-upload via `POST /api/clusters/import` to update
      the stored clusters. Same edit-via-CSV pattern as the existing LEAF data
      update flow.
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
        block = request.args.get('block')
        commodity = request.args.get('commodity')
        district = request.args.get('district')
        clusters = get_clusters(
            block_name=block,
            commodity=commodity,
            district_name=district,
        )
        # Mirror the lazy materialise in /api/clusters so the download CSV is
        # never empty on first request for a freshly ingested block. Re-read
        # through get_clusters afterwards so the rows carry the derived
        # cluster_num/cluster_label/cluster_code fields (the raw regenerate
        # payload has none of them).
        if not clusters and block:
            regenerate_clusters(block_name=block, commodity=commodity)
            clusters = get_clusters(
                block_name=block,
                commodity=commodity,
                district_name=district,
            )
        csv_text = clusters_to_csv(clusters)
        scope = block or district or 'all'
        return Response(
            csv_text,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=clusters_{scope}.csv'},
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@clusters_bp.route('/api/clusters/import', methods=['POST'])
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
      recomputed. When a row's `vill_name` is unknown to the village master,
      the row's `lat`/`long` are accepted as the coordinates for that new
      village (LEAF-44); when `lat`/`long` are omitted, the parser still backfills
      from the master for known villages, and fails fast with a clear error if
      it can't (legacy schema). Re-upload as many times as needed.
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

