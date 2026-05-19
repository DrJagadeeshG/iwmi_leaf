"""Admin guard tests covering the 9 May 2026 change (#9).

POST /api/clusters/regenerate must return 403 unless the caller passes
?admin=1 or X-Admin: 1. The guard runs *before* any database access, so
these tests don't need a live Postgres - we only inspect the 4xx path.
"""
import pytest


@pytest.fixture
def client():
    """Flask test client. Imports app lazily so import-time DB side effects
    don't break the rest of the suite if the env isn't fully configured."""
    import app as app_module
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


def test_regenerate_rejects_without_admin_flag(client):
    r = client.post('/api/clusters/regenerate', json={'block': 'NOWHERE'})
    assert r.status_code == 403, r.data
    body = r.get_json() or {}
    assert 'Admin' in body.get('error', ''), body


def test_regenerate_accepts_query_admin_flag(client, monkeypatch):
    """With ?admin=1 the guard lets the request through to the handler.
    We monkeypatch regenerate_clusters to avoid hitting the DB - the only
    thing under test here is that the guard doesn't block the call."""
    import app as app_module
    monkeypatch.setattr(app_module, 'regenerate_clusters',
                        lambda **kwargs: [])
    r = client.post('/api/clusters/regenerate?admin=1',
                    json={'block': 'NOWHERE'})
    assert r.status_code == 200, r.data
    assert r.get_json() == {'count': 0, 'clusters': []}


def test_regenerate_accepts_header_admin_flag(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, 'regenerate_clusters',
                        lambda **kwargs: [])
    r = client.post('/api/clusters/regenerate',
                    json={'block': 'NOWHERE'},
                    headers={'X-Admin': '1'})
    assert r.status_code == 200, r.data


def test_is_admin_request_helper_truth_table(client):
    """Direct unit test of the helper. Run inside a test request context
    so flask.request works."""
    import app as app_module
    with app_module.app.test_request_context('/?admin=1'):
        assert app_module._is_admin_request() is True
    with app_module.app.test_request_context('/', headers={'X-Admin': '1'}):
        assert app_module._is_admin_request() is True
    with app_module.app.test_request_context('/'):
        assert app_module._is_admin_request() is False
    with app_module.app.test_request_context('/?admin=0'):
        assert app_module._is_admin_request() is False
