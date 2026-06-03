"""Blueprint: export routes (split from app.py)."""
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

export_bp = Blueprint("export", __name__)


@export_bp.route('/api/export/csv', methods=['POST'])
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
            gdf = add_feasibility_to_gdf(gdf, filters)

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

