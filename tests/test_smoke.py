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


def test_user_update_overlay_is_no_op_when_unconfigured(monkeypatch):
    """LEAF-59: when the user_update sheet URL is empty (Faiz hasn't published
    yet), get_block_values_overlaid must return the coded block_values sheet
    unmodified — the rest of the pipeline keeps working until the sheet exists."""
    import pandas as pd
    import google_sheets as gs

    fake_bv = pd.DataFrame([
        {"Block_name": "BHERGAON", "BF": 12, "BG": 3},
        {"Block_name": "KHOWANG",  "BF": 0,  "BG": 0},
    ])
    monkeypatch.setattr(gs, "get_sheet",
                        lambda key: fake_bv if key == "block_values" else None)
    out = gs.get_block_values_overlaid()
    assert out is not None
    assert list(out["Block_name"]) == ["BHERGAON", "KHOWANG"]
    assert list(out["BF"]) == [12, 0]


def test_user_update_overlay_overlays_friendly_columns(monkeypatch):
    """LEAF-59: friendly columns in the user_update sheet overwrite the
    matching coded columns in block_values, joined case-insensitively on
    Block_name. Other rows / columns are untouched."""
    import pandas as pd
    import google_sheets as gs

    fake_bv = pd.DataFrame([
        {"Block_name": "BHERGAON", "BF": 0, "BI": 5, "BX": 100},
        {"Block_name": "KHOWANG",  "BF": 0, "BI": 0, "BX": 50},
    ])
    fake_user = pd.DataFrame([
        # Mixed-case Block_name should still join.
        {"Block_name": "Bhergaon",
         "Cattle density (per 100 hectares)": 25,
         "Goat density (per 100 hectares)":   18,
         "Total households":                  150},
    ])
    monkeypatch.setattr(gs, "get_sheet",
        lambda key: {"block_values": fake_bv, "user_update": fake_user}.get(key))

    out = gs.get_block_values_overlaid()
    bhergaon = out[out["Block_name"] == "BHERGAON"].iloc[0]
    khowang  = out[out["Block_name"] == "KHOWANG"].iloc[0]
    assert bhergaon["BF"] == 25 and bhergaon["BI"] == 18 and bhergaon["BX"] == 150
    # KHOWANG was not in the user sheet — values untouched.
    assert khowang["BF"] == 0 and khowang["BI"] == 0 and khowang["BX"] == 50
