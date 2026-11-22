"""Channel listing must be workspace-scoped and never expose credentials."""
from contextlib import contextmanager
import sqlite3
from datetime import datetime, timedelta
import pytest
from app.common import Pagination

from fastapi.testclient import TestClient

from app.dependencies import current_user
from app.main import create_app
from app.modules import channels
import app.dependencies as dependencies
from app.errors import ApiError


def test_browser_oauth_callback_returns_to_workspace_and_preserves_api_contract(monkeypatch):
    data = {
        'workspace_id': '1',
        'connection_token': 'temporary',
        'accounts': [{'account_name': '</script><script>alert(1)</script>'}],
    }

    def finish(platform, state, code, error):
        if error:
            raise ApiError(400, 'OAUTH_DENIED', 'Quyền truy cập bị từ chối')
        return {'data': data}

    monkeypatch.setattr(channels, 'finish_oauth', finish)
    client = TestClient(create_app())
    callback = '/api/v1/oauth/facebook/callback'
    assert client.get(callback, params={'state': 'api-state', 'code': 'mock'}).json() == {'data': data}

    response = client.get(callback, params={'state': 'ui.browser-state', 'code': 'mock'})
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['cache-control'] == 'no-store'
    assert 'orbitspace-oauth-result' in response.text
    assert 'location.replace' in response.text
    assert 'temporary' in response.text
    assert '<script>alert(1)' not in response.text

    denied = client.get(callback, params={'state': 'ui.browser-state', 'error': 'access_denied'})
    assert 'orbitspace-oauth-result' in denied.text
    assert '"error":' in denied.text
    assert 'temporary' not in denied.text


def test_channel_list_checks_membership_and_scopes_query(monkeypatch):
    class FakeDB:
        def one(self, sql, args=()):
            assert 'workspace_members' in sql
            return {'role_id': '5', 'role_code': 'viewer'} if args[0] == '1' else None

        def all(self, sql, args=()):
            assert 'a.workspace_id=%s' in sql
            assert args == ('1', 20, 0)
            assert 't.expires_at<=UTC_TIMESTAMP()' in sql
            assert 't.social_account_id IS NULL' in sql
            assert "a.status<>'connected'" in sql
            assert 'access_token_enc' not in sql
            assert 'refresh_token_enc' not in sql
            return [{'workspace_id': '1', 'account_name': 'Team page', 'connection_status': 'expired'}]

    @contextmanager
    def transaction():
        yield FakeDB()

    monkeypatch.setattr(channels, 'transaction', transaction)
    monkeypatch.setattr(dependencies, 'transaction', transaction)
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {'user_id': '2'}
    client = TestClient(app)
    response = client.get('/api/v1/workspaces/1/social-accounts')
    assert response.status_code == 200
    assert response.json()['data'][0]['workspace_id'] == '1'
    assert client.get('/api/v1/workspaces/2/social-accounts').status_code == 404


def test_channel_list_requires_login():
    client = TestClient(create_app())
    assert client.get('/api/v1/workspaces/1/social-accounts').status_code == 401

# Run the listing query against small fixtures, including expired/missing tokens.


@pytest.mark.parametrize('stored_status,token_state,expected', [
    ('connected', 'valid', 'connected'),
    ('connected', 'expired', 'expired'),
    ('connected', 'missing', 'expired'),
    ('connected', 'no_expiry', 'connected'),
    ('expired', 'valid', 'expired'),
    ('error', 'valid', 'error'),
    ('disconnected', 'missing', 'disconnected'),
])
def test_effective_connection_status(monkeypatch, stored_status, token_state, expected):
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.create_function('UTC_TIMESTAMP', 0, lambda: datetime.now().isoformat(' '))
    connection.executescript('''
        CREATE TABLE platforms(platform_id INTEGER, code TEXT);
        CREATE TABLE social_accounts(social_account_id INTEGER, workspace_id TEXT, platform_id INTEGER, status TEXT);
        CREATE TABLE social_account_tokens(social_account_id INTEGER, expires_at TEXT, scopes TEXT);
        INSERT INTO platforms VALUES (1, 'facebook');
        INSERT INTO social_accounts VALUES (2, 'other-workspace', 1, 'connected');
    ''')
    connection.execute('INSERT INTO social_accounts VALUES (1, ?, 1, ?)', ('1', stored_status))
    if token_state != 'missing':
        expires = None if token_state == 'no_expiry' else (
            datetime.now() + timedelta(days=-1 if token_state == 'expired' else 1)
        ).isoformat(' ')
        connection.execute('INSERT INTO social_account_tokens VALUES (1, ?, NULL)', (expires,))

    class FakeDB:
        def all(self, sql, args):
            return [dict(row) for row in connection.execute(sql.replace('%s', '?'), args)]

    @contextmanager
    def transaction():
        yield FakeDB()

    monkeypatch.setattr(channels, 'transaction', transaction)
    try:
        rows = channels.list_accounts('1', Pagination())['data']
        assert len(rows) == 1
        assert rows[0]['connection_status'] == expected
        assert rows[0]['workspace_id'] == '1'
    finally:
        connection.close()
