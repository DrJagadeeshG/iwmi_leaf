"""Smoke tests that catch import-time and obvious wiring breaks.

If any of these fail, the app won't start at all - useful as a first-line
canary before deeper test failures muddy the picture.
"""


def test_app_module_imports():
    """The Flask app must import without raising. Catches syntax errors,
    bad imports, and module-level wiring problems."""
    import app  # noqa: F401


def test_clustering_module_imports_and_defaults_sane():
    import clustering
    # Sanity-check the defaults the side panel's rule explanation depends on.
    p = clustering.DEFAULT_PARAMS
    assert p['min_cluster_members'] < p['max_cluster_members']
    assert p['max_radius_km'] > 0
    # LEAF-43: village-count band removed; both keys must be gone.
    assert 'min_villages_per_cluster' not in p
    assert 'max_villages_per_cluster' not in p


def test_villages_csv_helpers_present():
    """The CSV helpers must be exported - they're imported by app.py at
    module load and a missing export would surface as ImportError there."""
    import villages
    for name in ('clusters_to_csv', 'csv_text_to_records',
                 'get_clusters', 'get_cluster', 'regenerate_clusters'):
        assert hasattr(villages, name), f"villages.{name} missing"


def test_flask_routes_registered():
    """All cluster-related routes registered on the app."""
    import app as app_module
    routes = {str(r) for r in app_module.app.url_map.iter_rules()}
    for path in (
        '/api/clusters',
        '/api/clusters/regenerate',
        '/api/clusters/export.csv',
        '/api/clusters/import',
    ):
        assert any(path in r for r in routes), f"route {path} not registered"
