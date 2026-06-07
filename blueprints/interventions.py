"""Blueprint: interventions routes (split from app.py)."""
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

interventions_bp = Blueprint("interventions", __name__)


@interventions_bp.route('/api/interventions')
def api_interventions():
    """List available interventions.
    ---
    tags:
      - Interventions
    summary: Get all interventions
    description: >
      Returns the list of available agricultural interventions auto-detected from
      the CSV configuration. Interventions may form a one-level hierarchy via the
      optional `parent` column: a sub-category (e.g. Goatery) carries `parent`
      (e.g. Livestock), and a parent lists its `children`. Top-level interventions
      have `parent: null`.
    responses:
      200:
        description: List of interventions
        schema:
          type: object
          properties:
            interventions:
              type: array
              items:
                type: object
                properties:
                  key:
                    type: string
                  name:
                    type: string
                  description:
                    type: string
                  parent:
                    type: string
                    description: Parent intervention name, or null for top-level
                  children:
                    type: array
                    items:
                      type: string
                    description: Sub-category names (only on parents)
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        interventions = get_interventions()
        interventions_list = [
            {
                'key': val['key'],
                'name': val['name'],
                'description': val['description'],
                'parent': val.get('parent'),
                'children': val.get('children', []),
            }
            for val in interventions.values()
        ]
        return jsonify({'interventions': interventions_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@interventions_bp.route('/api/livestock-subfilter.csv')
def api_livestock_subfilter_csv():
    """Download the effective Livestock sub-filter configuration as CSV.
    ---
    tags:
      - Interventions
    summary: Export livestock sub-filter CSV
    description: |
      Returns the Livestock sub-category configuration rows (Dairy, Goatery,
      Piggery, Backyard_Poultry, Duckery, Fishery_Activity) currently in
      effect - one row per (sub-type, variable) with the same columns as the
      Intervention & Variable Config sheet plus the `parent` column
      (always `Livestock`).

      Source resolution mirrors the runtime overlay (LEAF-51): when the
      dss_input Google Sheet itself declares all six sub-types as Livestock
      children, the sheet's rows are returned; otherwise the app's built-in
      defaults are returned. To edit the sub-filter, download this CSV, adjust
      the ranges/weights/labels, paste the rows into the Intervention &
      Variable Config Google Sheet, and hit Refresh on the /update page -
      once the sheet declares all six sub-types it owns the configuration and
      the built-in defaults are ignored.
    responses:
      200:
        description: CSV file (columns of the dss_input sheet + parent)
        schema: {type: string}
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        df = load_metadata()
        if 'parent' in df.columns:
            rows = df[df['parent'].astype(str).str.strip().str.lower() == 'livestock']
        else:
            rows = df.iloc[0:0]
        return Response(
            rows.to_csv(index=False),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=livestock_subfilter.csv'},
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@interventions_bp.route('/api/livestock-subfilter', methods=['POST'])
def api_upload_livestock_subfilter():
    """Upload a new Livestock sub-filter configuration CSV (admin only).
    ---
    tags:
      - Interventions
    summary: Upload livestock sub-filter CSV
    description: >
      Admin-only. Accepts an edited Livestock sub-filter CSV (the file produced
      by `GET /api/livestock-subfilter.csv`) as multipart/form-data field
      `file`, validates it, and persists it to the app's sub-filter store
      (`data/livestock_subfilter.csv`). The dss_input cache is then refreshed so
      the new ranges/weights/labels take effect immediately, with no redeploy.

      This makes the six Livestock commodities (Dairy, Goatery, Piggery,
      Backyard_Poultry, Duckery, Fishery_Activity) fully data-driven from the
      /update page: download, edit, upload. The stored CSV is the overlay source
      used whenever the dss_input Google Sheet does not itself declare all six
      sub-types as Livestock children. Requires the admin guard (`?admin=1`
      query param or `X-Admin: 1` header).

      Validation rejects the upload (400) unless: the required columns
      (Cluster, I_variable, range_min, range_max, parent) are present; every
      row has parent=Livestock; all six commodities are present with at least
      one variable row each; and range_min/range_max are numeric with
      range_min <= range_max.
    consumes:
      - multipart/form-data
    parameters:
      - in: formData
        name: file
        type: file
        required: true
        description: The edited Livestock sub-filter CSV.
    responses:
      200:
        description: Upload accepted and persisted; config now in effect.
        schema:
          type: object
          properties:
            ok:
              type: boolean
            rows:
              type: integer
              description: Number of data rows persisted.
            message:
              type: string
      400:
        description: No file provided, or the CSV failed validation.
        schema:
          $ref: '#/definitions/Error'
      403:
        description: Caller is not an admin.
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error while saving the configuration.
        schema:
          $ref: '#/definitions/Error'
    """
    from data_utils import validate_livestock_subfilter_csv, save_livestock_subfilter_csv

    if not _is_admin_request():
        return jsonify({'error': 'Admin access required.'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided. Use multipart/form-data field "file".'}), 400

    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'No file selected.'}), 400

    try:
        text = upload.read().decode('utf-8-sig')
    except Exception:
        return jsonify({'error': 'Could not read the file as UTF-8 text.'}), 400

    df, error = validate_livestock_subfilter_csv(text)
    if error:
        return jsonify({'error': error}), 400

    try:
        save_livestock_subfilter_csv(df)
        # Drop the dss_input cache so the overlay re-reads the new file at once.
        from google_sheets import refresh
        refresh('dss_input')
    except Exception as e:
        return jsonify({'error': f'Failed to save the configuration: {e}'}), 500

    return jsonify({
        'ok': True,
        'rows': int(len(df)),
        'message': 'Livestock sub-filter updated. The new configuration is now in effect.',
    })




@interventions_bp.route('/api/variables')
def api_variables():
    """Get all available variables from the shapefile.
    ---
    tags:
      - Variables
    summary: Get all block-level variables
    description: Returns metadata for all numeric variables available in the block-level shapefile, including min/max/mean statistics.
    responses:
      200:
        description: Array of variable metadata
        schema:
          type: array
          items:
            $ref: '#/definitions/VariableMetadata'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        gdf = load_shapefile()
        metadata = get_variable_metadata()

        # Load CSV to get group info
        csv_df = load_metadata()
        # Create a mapping of variable to group (use 'variable' column, not 'I_variable')
        var_to_group = {}
        for _, row in csv_df.iterrows():
            var = row.get('variable')
            group = row.get('group')
            if pd.notna(var) and pd.notna(group) and var not in var_to_group:
                var_to_group[str(var).strip()] = str(group).strip()

        variables = []
        # Get numeric columns from shapefile
        for col in gdf.columns:
            if col in ['geometry', 'BLOCK_ID', 'STATE_ID', 'DISTRICT_I', 'Block_name', 'id']:
                continue

            series = pd.to_numeric(gdf[col], errors='coerce')
            if series.notna().sum() > 0:  # Has numeric data
                meta = metadata.get(col, {})
                variables.append({
                    'field': col,
                    'label': meta.get('label', col),
                    'description': meta.get('description', ''),
                    'group': var_to_group.get(col, 'Other'),
                    'data_min': float(series.min()) if pd.notna(series.min()) else 0,
                    'data_max': float(series.max()) if pd.notna(series.max()) else 100,
                    'data_mean': float(series.mean()) if pd.notna(series.mean()) else 50,
                })

        return jsonify(variables)
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@interventions_bp.route('/api/intervention/<name>/config')
def api_intervention_config(name):
    """Get configuration for a specific intervention.
    ---
    tags:
      - Interventions
    summary: Get intervention configuration
    description: Returns the variable filters and weights configured for the specified intervention.
    parameters:
      - name: name
        in: path
        type: string
        required: true
        description: Intervention key name (e.g. "Organic Farming")
    responses:
      200:
        description: Intervention configuration
        schema:
          type: object
          properties:
            intervention:
              type: string
            name:
              type: string
            description:
              type: string
            variables:
              type: array
              items:
                type: object
      404:
        description: Intervention not found
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        config = get_intervention_config()

        if name not in config:
            return jsonify({'error': f'Intervention "{name}" not found'}), 404

        variables = config[name]
        interventions = get_interventions()
        intervention_info = interventions.get(name, {})

        return jsonify({
            'intervention': name,
            'name': intervention_info.get('name', name),
            'description': intervention_info.get('description', ''),
            'variables': variables
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@interventions_bp.route('/api/variable-groups')
def api_variable_groups():
    """List available variable groups.
    ---
    tags:
      - Variables
    summary: Get variable groups
    description: Returns the list of variable group categories.
    responses:
      200:
        description: Variable groups
        schema:
          type: object
          properties:
            groups:
              type: array
              items:
                type: object
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        groups = get_variable_groups()
        return jsonify({'groups': groups})
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@interventions_bp.route('/api/variable-stats/<variable>')
def api_variable_stats(variable):
    """Get min/max/mean for a variable.
    ---
    tags:
      - Variables
    summary: Get variable statistics
    description: Returns min, max, and mean values for the specified variable column.
    parameters:
      - name: variable
        in: path
        type: string
        required: true
        description: Variable/column name
    responses:
      200:
        description: Variable statistics
        schema:
          type: object
          properties:
            min:
              type: number
            max:
              type: number
            mean:
              type: number
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        stats = get_column_stats(variable)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Feasibility Calculation APIs
# =============================================================================

