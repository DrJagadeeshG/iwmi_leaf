"""Blueprint: infrastructure routes (split from app.py)."""
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

infrastructure_bp = Blueprint("infrastructure", __name__)


@infrastructure_bp.route('/api/infrastructure')
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




@infrastructure_bp.route('/api/infrastructure/import', methods=['POST'])
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




@infrastructure_bp.route('/api/infrastructure/nearest')
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

