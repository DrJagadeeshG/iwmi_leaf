"""Blueprint: levels routes (split from app.py)."""
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

levels_bp = Blueprint("levels", __name__)


@levels_bp.route('/api/levels')
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



@levels_bp.route('/health')
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




@levels_bp.route('/ai-docs/<path:filename>')
def serve_ai_docs(filename):
    """Serve AI policy documents (PDFs)."""
    from pathlib import Path
    ai_docs_dir = Path(__file__).parent.parent / "ai-docs"
    return send_from_directory(ai_docs_dir, filename)




@levels_bp.route('/documentation/')
@levels_bp.route('/documentation/<path:filename>')
def serve_documentation(filename='index.html'):
    """Serve the MkDocs documentation site."""
    from pathlib import Path
    # This file lives in blueprints/; the built MkDocs site is at the app root
    # (mkdocs.yml site_dir: leaf_flask/site), so go up TWO levels, not one.
    # Previously resolved to blueprints/site (non-existent) -> /documentation 404'd.
    site_dir = Path(__file__).parent.parent / "site"
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


