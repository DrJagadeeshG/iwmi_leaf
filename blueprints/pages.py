"""Blueprint: pages routes (split from app.py)."""
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

pages_bp = Blueprint("pages", __name__)




@pages_bp.route('/')
def index():
    """Main dashboard page."""
    return render_app()




@pages_bp.route('/clustering')
@pages_bp.route('/clustering/')
@pages_bp.route('/clustering/<block>')
def clustering_page(block=None):
    """Standalone cluster-planning workspace as a full page (rather than a modal).
    Same UI as the in-block modal - useful for shareable links and side-by-side
    comparisons across blocks. `block` is optional; defaults to the first block
    that has village data ingested.
    """
    return render_template(
        'clustering.html',
        initial_block=block or '',
        initial_commodity=request.args.get('commodity', ''),
    )




@pages_bp.route('/update')
@pages_bp.route('/update/')
def update_page():
    """Data update page - shows Google Sheet links and refresh controls."""
    from google_sheets import get_status, SHEET_URLS
    return render_template('update.html',
                           status=get_status(),
                           sheet_urls=SHEET_URLS,
                           colors=COLORS)




@pages_bp.route('/about')
@pages_bp.route('/about/')
def about_page():
    """About page - describes the LEAF DSS, its features, data and partners."""
    return render_template('about.html')




@pages_bp.route('/<district>')
def district_view(district):
    """District level view (shows all blocks in district)."""
    from flask import redirect, url_for
    # Reserved paths - let their own routes handle them
    if district in ('documentation', 'docs', 'api', 'static', 'health', 'update', 'clustering', 'about'):
        return redirect(f'/{district}/')
    gdf = load_shapefile()
    valid_districts = gdf['Dist_Name'].dropna().unique().tolist()
    if district not in valid_districts:
        return jsonify({'error': 'Invalid route'}), 404
    return render_app(level='block', district=district)




@pages_bp.route('/<district>/<block>')
def block_detail_view(district, block):
    """Block detail view: /district/block."""
    return render_app(level='block', district=district, block=block)




@pages_bp.route('/<district>/<block>/clustering')
def clustering_block_nested(district, block):
    """Cluster planning workspace nested under block detail: /district/block/clustering."""
    return render_template(
        'clustering.html',
        initial_block=block,
        initial_district=district,
        initial_commodity=request.args.get('commodity', ''),
    )




@pages_bp.route('/<district>/<block>/<gp>')
def gp_detail_view(district, block, gp):
    """GP detail view: /district/block/gp_name."""
    if gp == 'clustering':  # safety net - explicit route above should win first
        return clustering_block_nested(district, block)
    return render_app(level='gp', district=district, block=block, gp=gp)


# =============================================================================
# Data Loading APIs - Block Level
# =============================================================================

