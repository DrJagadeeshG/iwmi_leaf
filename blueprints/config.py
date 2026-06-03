"""Blueprint: config routes (split from app.py)."""
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

config_bp = Blueprint("config", __name__)


@config_bp.route('/api/config')
def api_config():
    """Get app configuration (colors, thresholds, etc.).
    ---
    tags:
      - Config
    summary: Get application configuration
    description: Returns color schemes, feasibility color thresholds, and map configuration.
    responses:
      200:
        description: Application configuration
        schema:
          type: object
          properties:
            colors:
              type: object
            feasibility_colors:
              type: object
            map_config:
              type: object
    """
    return jsonify({
        'colors': COLORS,
        'feasibility_colors': FEASIBILITY_COLORS,
        'map_config': MAP_CONFIG,
    })




@config_bp.route('/api/config/refresh', methods=['POST'])
def api_config_refresh():
    """Force-refresh data from Google Sheets.
    ---
    tags:
      - Config
    summary: Refresh Google Sheets data
    description: Forces a re-fetch of all data from published Google Sheets, bypassing the TTL cache.
    responses:
      200:
        description: Refresh results
        schema:
          type: object
          properties:
            refreshed:
              type: object
              description: Map of sheet key to success boolean
            status:
              type: object
              description: Current cache status after refresh
            validation:
              type: object
              description: Guardrail validation result (ok flag + list of issues)
    """
    from google_sheets import refresh, get_status, validate_sheets
    results = refresh()
    return jsonify({
        'refreshed': results,
        'status': get_status(),
        'validation': validate_sheets(),
    })




@config_bp.route('/api/config/sheets-status')
def api_sheets_status():
    """Get Google Sheets cache status.
    ---
    tags:
      - Config
    summary: Get Google Sheets sync status
    description: Returns the current cache status for all Google Sheet data sources.
    responses:
      200:
        description: Cache status for each sheet
        schema:
          type: object
    """
    from google_sheets import get_status
    return jsonify(get_status())




@config_bp.route('/api/config/validate')
def api_config_validate():
    """Validate the config sheets (guardrails).
    ---
    tags:
      - Config
    summary: Validate Google Sheets structure
    description: >
      Runs structural guardrail checks (LEAF-60) on the intervention config and
      block values sheets - missing/renamed ID columns, duplicate BLOCK_IDs,
      non-numeric values in numeric columns, range_min > range_max, and
      I_variable codes that do not exist in the block values sheet. Read-only.
    responses:
      200:
        description: Validation result
        schema:
          type: object
          properties:
            ok:
              type: boolean
              description: false if any error-severity issue was found
            issues:
              type: array
              items:
                type: object
                properties:
                  sheet:
                    type: string
                  severity:
                    type: string
                    enum: [error, warning]
                  message:
                    type: string
    """
    from google_sheets import validate_sheets
    return jsonify(validate_sheets())




@config_bp.route('/api/config/upload-ai-doc', methods=['POST'])
def api_upload_ai_doc():
    """Upload a PDF to the AI knowledge base (admin only).
    ---
    tags:
      - Config
    summary: Upload an AI knowledge-base document
    description: >
      Admin-only. Accepts a single PDF file (multipart/form-data, field name
      `file`), saves it into the `ai-docs/` retrieval pool, and deletes the
      persisted vector store so the next `POST /api/ai-recommendation` call
      lazily rebuilds the embeddings to include the new document. The
      re-embedding is deferred to that next call, so this endpoint returns
      immediately and does not block. Requires the admin guard (`?admin=1`
      query param or `X-Admin: 1` header).
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: The PDF document to add to the knowledge base.
    responses:
      200:
        description: Upload accepted; vector store scheduled for lazy rebuild.
        schema:
          type: object
          properties:
            ok:
              type: boolean
            filename:
              type: string
              description: Sanitized name the file was saved under.
            message:
              type: string
      400:
        description: No file provided, or the file is not a PDF.
        schema:
          $ref: '#/definitions/Error'
      403:
        description: Caller is not an admin.
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error while saving the document.
        schema:
          $ref: '#/definitions/Error'
    """
    import os
    from werkzeug.utils import secure_filename
    from rag_utils import AI_DOCS_DIR, reset_vectorstore

    if not _is_admin_request():
        return jsonify({'error': 'Admin access required.'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided. Use multipart/form-data field "file".'}), 400

    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'No file selected.'}), 400

    filename = secure_filename(upload.filename)
    if not filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF documents are accepted.'}), 400

    try:
        os.makedirs(AI_DOCS_DIR, exist_ok=True)
        upload.save(os.path.join(str(AI_DOCS_DIR), filename))
        # Lazy rebuild: wipe the persisted store so the next AI call re-embeds.
        reset_vectorstore()
    except Exception as e:
        return jsonify({'error': f'Failed to save document: {e}'}), 500

    return jsonify({
        'ok': True,
        'filename': filename,
        'message': 'Document added. AI knowledge base will rebuild on the next recommendation request.',
    })


# =============================================================================
# GP (Gram Panchayat) Level APIs
# =============================================================================

