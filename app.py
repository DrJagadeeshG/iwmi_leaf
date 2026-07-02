"""
LEAF DSS - Flask Application
Decision Support System for Agricultural Interventions
"""

import os
import json

# Load .env early so DATABASE_URL is available before any module imports it.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass

from flask import Flask, render_template, jsonify, request, Response, send_from_directory
from flask_cors import CORS
from flasgger import Swagger
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
    # GP-level functions
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

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Swagger / OpenAPI configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: rule.rule.startswith('/api') or rule.rule == '/health',
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "info": {
        "title": "LEAF DSS API",
        "version": "1.0.0",
        "description": (
            "Decision Support System for Agricultural Interventions in Assam, India. "
            "Provides block-level and GP-level geospatial data, feasibility analysis, "
            "and AI-powered recommendations."
        ),
    },
    "tags": [
        {"name": "Blocks", "description": "Block-level geospatial data and lookups"},
        {"name": "Locations", "description": "Hierarchical location data (districts, blocks, GPs)"},
        {"name": "GPs", "description": "Gram Panchayat level data and lookups"},
        {"name": "Interventions", "description": "Agricultural intervention definitions and configurations"},
        {"name": "Variables", "description": "Data variable metadata and statistics"},
        {"name": "Feasibility", "description": "Feasibility score calculation endpoints"},
        {"name": "AI", "description": "AI-powered recommendation engine (RAG-based)"},
        {"name": "Export", "description": "Data export endpoints"},
        {"name": "Config", "description": "Application configuration and metadata"},
        {"name": "Villages", "description": "Village-level point data (ODK / MMUA seed) for cluster generation"},
        {"name": "Clusters", "description": "Per-commodity village clusters: generation, retrieval, CSV edit cycle"},
        {"name": "Infrastructure", "description": "Vet centres, pharmacies, input shops - POI database with nearest-to-cluster query"},
        {"name": "ProductionTool", "description": "Outbound feed of finalised clusters and inbound dashboard data exchange with the external production tool"},
        {"name": "Deprecated", "description": "Deprecated endpoints - use newer alternatives"},
    ],
    "definitions": {
        "Error": {
            "type": "object",
            "properties": {
                "error": {"type": "string", "description": "Error message"}
            }
        },
        "FilterCriteria": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Variable/column name"},
                "min_val": {"type": "number", "description": "Minimum threshold"},
                "max_val": {"type": "number", "description": "Maximum threshold"},
                "weight": {"type": "number", "description": "Weight for scoring (0-1)", "default": 1.0}
            }
        },
        "VariableMetadata": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "label": {"type": "string"},
                "description": {"type": "string"},
                "group": {"type": "string"},
                "data_min": {"type": "number"},
                "data_max": {"type": "number"},
                "data_mean": {"type": "number"}
            }
        },
        "FeasibilityResult": {
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "GeoJSON FeatureCollection with feasibility scores"},
                "statistics": {"type": "object", "description": "Distribution statistics"},
                "filters_applied": {"type": "array", "items": {"$ref": "#/definitions/FilterCriteria"}}
            }
        }
    }
}

Swagger(app, config=swagger_config, template=swagger_template)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'iwmi-leaf-secret-key')


# Import shared helpers (moved out of app.py to avoid circular imports)
from shared import get_rag_utils, render_app, _is_admin_request, _cluster_params_from_request

# Re-export so existing tests/callers can monkeypatch app.regenerate_clusters;
# the clusters blueprint resolves the symbol through this module at call time.
from villages import regenerate_clusters

# Register blueprints
from blueprints.pages import pages_bp
from blueprints.blocks import blocks_bp
from blueprints.locations import locations_bp
from blueprints.interventions import interventions_bp
from blueprints.feasibility import feasibility_bp
from blueprints.export import export_bp
from blueprints.config import config_bp
from blueprints.gp import gp_bp
from blueprints.levels import levels_bp
from blueprints.villages import villages_bp
from blueprints.clusters import clusters_bp
from blueprints.infrastructure import infrastructure_bp
from blueprints.production_tool import production_tool_bp
from blueprints.api_info import api_info_bp

app.register_blueprint(pages_bp)
app.register_blueprint(blocks_bp)
app.register_blueprint(locations_bp)
app.register_blueprint(interventions_bp)
app.register_blueprint(feasibility_bp)
app.register_blueprint(export_bp)
app.register_blueprint(config_bp)
app.register_blueprint(gp_bp)
app.register_blueprint(levels_bp)
app.register_blueprint(villages_bp)
app.register_blueprint(clusters_bp)
app.register_blueprint(infrastructure_bp)
app.register_blueprint(production_tool_bp)
app.register_blueprint(api_info_bp)


# Daily maintenance: rebuild whole-state cluster coverage so the export/report
# reflects every block, not just the ones opened in the UI. Idempotent and
# advisory-locked, so it is safe under multiple gunicorn workers and starting it
# at import (once per process) is enough. The manual trigger is the "Refresh all
# clusters" button (POST /api/clusters/refresh-all).
from scheduler import start_scheduler
start_scheduler()


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    # Check if it's an API request
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Endpoint not found', 'path': request.path}), 404
    # For non-API requests, return the main app (SPA style)
    return render_app()


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=5000, debug=True)
