"""Shared helpers extracted from app.py.

Lives outside app.py so blueprints can import these without importing the Flask
app object (avoids circular imports). Must NOT import app.
"""
from flask import render_template, request

from config import COLORS, VARIABLE_GROUPS, MAP_CONFIG
from data_utils import get_interventions
from clustering import DEFAULT_PARAMS


# RAG utilities for AI recommendations (lazy import to avoid startup delay)
rag_utils = None
def get_rag_utils():
    global rag_utils
    if rag_utils is None:
        try:
            from rag_utils import generate_recommendation, initialize_vectorstore
            rag_utils = {'generate': generate_recommendation, 'init': initialize_vectorstore}
        except ImportError as e:
            print(f"RAG utilities not available: {e}")
            rag_utils = {'error': str(e)}
    return rag_utils


def render_app(level='block', district='', block='', gp=''):
    """Common render function for the app."""
    return render_template('index.html',
                           interventions=get_interventions(),
                           variable_groups=VARIABLE_GROUPS,
                           colors=COLORS,
                           map_config=MAP_CONFIG,
                           initial_level=level,
                           initial_district=district,
                           initial_block=block,
                           initial_gp=gp)


def _is_admin_request() -> bool:
    """Admin-only API guard. No real auth in this app, but Faiz wanted Regenerate
    hidden from regular users (2026-05-09 call) because it wipes their CSV edits.
    Mirrors the IS_ADMIN flag in static/js/clusters.js: query `?admin=1` or
    header `X-Admin: 1`. Defense-in-depth alongside the JS-side button hide.
    """
    if request.args.get('admin') == '1':
        return True
    if request.headers.get('X-Admin') == '1':
        return True
    return False


def _cluster_params_from_request():
    """Pull tunable clustering params from query string or JSON body, applying defaults."""
    src = {}
    src.update({k: request.args.get(k) for k in DEFAULT_PARAMS if request.args.get(k) is not None})
    if request.is_json:
        body = request.get_json(silent=True) or {}
        for k in DEFAULT_PARAMS:
            if k in body and body[k] is not None:
                src[k] = body[k]
    out = {}
    for k, default in DEFAULT_PARAMS.items():
        if k not in src:
            continue
        v = src[k]
        # bool must be checked before int (bool is an int subclass). Accept the
        # usual truthy strings from query params, and real bools from JSON.
        if isinstance(default, bool):
            out[k] = v in (True, 1) or (isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"))
        elif isinstance(default, float):
            out[k] = float(v)
        else:
            out[k] = int(v)
    return out
