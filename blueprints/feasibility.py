"""Blueprint: feasibility routes (split from app.py)."""
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

feasibility_bp = Blueprint("feasibility", __name__)


@feasibility_bp.route('/api/calculate-feasibility', methods=['POST'])
def api_calculate_feasibility():
    """Calculate feasibility scores with custom filters.
    ---
    tags:
      - Feasibility
    summary: Calculate block-level feasibility
    description: Calculates feasibility scores for all blocks based on the provided variable filters and weights. Returns GeoJSON with scores and distribution statistics.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            intervention:
              type: string
              description: Intervention name (uses default config if no filters provided)
            filters:
              type: array
              description: Custom filter criteria
              items:
                $ref: '#/definitions/FilterCriteria'
            district:
              type: string
              description: Optional district ID to filter statistics
    responses:
      200:
        description: Feasibility results
        schema:
          $ref: '#/definitions/FeasibilityResult'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        data = request.get_json()

        intervention = data.get('intervention')
        filters = data.get('filters', [])
        district = data.get('district')

        # If intervention specified but no filters, use default intervention config
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

        # Load data and calculate
        gdf = load_shapefile()
        result = calculate_and_get_geojson(gdf, filters, district)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500




@feasibility_bp.route('/api/ai-recommendation', methods=['POST'])
def api_ai_recommendation():
    """Generate AI-powered recommendations based on block data and policy documents.
    ---
    tags:
      - AI
    summary: Get AI recommendation
    description: Uses RAG (Retrieval-Augmented Generation) to generate context-aware recommendations based on block data, feasibility scores, and policy documents.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            block_name:
              type: string
              description: Name of the block
              example: Digboi
            district_name:
              type: string
              description: Name of the district
              example: Tinsukia
            intervention:
              type: string
              description: Selected intervention name
            feasibility_score:
              type: number
              description: Current feasibility score
            metrics:
              type: array
              items:
                type: object
                properties:
                  label:
                    type: string
                  value:
                    type: number
                  in_range:
                    type: boolean
                  min:
                    type: number
                  max:
                    type: number
            filters:
              type: array
              items:
                $ref: '#/definitions/FilterCriteria'
    responses:
      200:
        description: AI recommendation
        schema:
          type: object
          properties:
            recommendation:
              type: string
            sources:
              type: array
              items:
                type: object
      503:
        description: RAG service unavailable
        schema:
          $ref: '#/definitions/Error'
      500:
        description: Server error
        schema:
          $ref: '#/definitions/Error'
    """
    try:
        rag = get_rag_utils()

        if 'error' in rag:
            return jsonify({
                'recommendation': 'AI recommendations are not available. Please install RAG dependencies.',
                'error': rag['error'],
                'sources': []
            }), 503

        data = request.get_json()

        block_name = data.get('block_name', 'Unknown')
        district_name = data.get('district_name', 'Unknown')
        intervention = data.get('intervention', '')
        feasibility_score = data.get('feasibility_score', 0)
        metrics = data.get('metrics', [])
        filters = data.get('filters', [])

        if not intervention:
            return jsonify({
                'recommendation': 'Please select an intervention to get AI recommendations.',
                'sources': []
            })

        result = rag['generate'](
            block_name=block_name,
            district_name=district_name,
            intervention=intervention,
            feasibility_score=feasibility_score,
            metrics=metrics,
            filters=filters
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'recommendation': f'Error generating recommendation: {str(e)}',
            'error': str(e),
            'sources': []
        }), 500




@feasibility_bp.route('/api/ai-recommendation/init', methods=['POST'])
def api_init_vectorstore():
    """Initialize/rebuild the vector store from PDF documents.
    ---
    tags:
      - AI
    summary: Initialize AI vector store
    description: Rebuilds the RAG vector store by processing PDF policy documents. Required before AI recommendations can be generated.
    responses:
      200:
        description: Initialization result
        schema:
          type: object
          properties:
            success:
              type: boolean
      503:
        description: RAG service unavailable
        schema:
          type: object
          properties:
            success:
              type: boolean
            error:
              type: string
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
            error:
              type: string
    """
    try:
        rag = get_rag_utils()

        if 'error' in rag:
            return jsonify({'success': False, 'error': rag['error']}), 503

        success = rag['init']()
        return jsonify({'success': success})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


