"""Browser accounts (api/accounts.py): registration, cookie sessions, role assignment."""
import json

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.accounts as accounts
    import api.auth as auth
    import api.main as main
    from config.settings import APISettings
    keys = tmp_path / "api_keys.yaml"
    keys.write_text(json.dumps({"users": [{"user_id": "bob", "role": "partner", "key_sha256": auth.hash_key("k1")}]}))
    settings = APISettings(api_keys_file=keys, allow_anonymous=True, users_file=tmp_path / "users.json",
                           role_assignments_file=tmp_path / "roles.json",
                           session_secret_file=tmp_path / "secret", session_ttl_s=3600)
    for module in (auth, main, accounts):
        monkeypatch.setattr(module, "API_SETTINGS", settings)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setattr(accounts, "_assignments_cache", {"mtime": None, "by_email": {}})
    monkeypatch.setattr(accounts, "_failed", {})
    return TestClient(main.app)


def set_roles(client, mapping):
    import api.accounts as accounts
    path = accounts.API_SETTINGS.role_assignments_file
    path.write_text(json.dumps(mapping))
    accounts._assignments_cache["mtime"] = None   # the test runs faster than mtime resolution


def test_register_starts_public_and_sets_httponly_cookie(client):
    r = client.post("/auth/register", json={"email": "New@Example.com", "password": "correct horse"})
    assert r.status_code == 201
    assert r.json() == {"user_id": "new@example.com", "role": "public", "tenant_id": "default",
                        "authenticated": True, "via": "session"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/whoami").json()["user_id"] == "new@example.com"
    import api.accounts as accounts
    stored = json.loads(accounts.API_SETTINGS.users_file.read_text())
    assert "correct horse" not in json.dumps(stored)          # only the scrypt hash is kept


def test_role_from_assignments_applies_live(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "password1"})
    set_roles(client, {"_comment": "x", "alice@example.com": "employee"})
    assert client.get("/whoami").json()["role"] == "employee"
    set_roles(client, {"alice@example.com": {"role": "partner", "tenant_id": "acme"}})
    me = client.get("/whoami").json()
    assert (me["role"], me["tenant_id"]) == ("partner", "acme")
    set_roles(client, {"alice@example.com": "superuser"})     # unknown role -> ignored -> default role
    assert client.get("/whoami").json()["role"] == "public"


def test_login_logout_and_wrong_password(client):
    client.post("/auth/register", json={"email": "c@example.com", "password": "password1"})
    client.post("/auth/logout", json={})
    assert client.get("/whoami").json()["via"] == "anonymous"
    assert client.post("/auth/login", json={"email": "c@example.com", "password": "nope-nope"}).status_code == 401
    assert client.post("/auth/login", json={"email": "ghost@example.com", "password": "password1"}).status_code == 401
    assert client.post("/auth/login", json={"email": "c@example.com", "password": "password1"}).status_code == 200
    assert client.get("/whoami").json()["user_id"] == "c@example.com"


def test_repeated_failed_logins_are_throttled(client):
    client.post("/auth/register", json={"email": "d@example.com", "password": "password1"})
    codes = [client.post("/auth/login", json={"email": "d@example.com", "password": "wrong-pass"}).status_code
             for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_register_validation(client):
    assert client.post("/auth/register", json={"email": "not-an-email", "password": "password1"}).status_code == 422
    assert client.post("/auth/register", json={"email": "e@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/register", json={"email": "e@example.com", "password": "password1"}).status_code == 201
    assert client.post("/auth/register", json={"email": "E@example.com", "password": "password1"}).status_code == 409
    # extra fields such as a self-chosen role are rejected
    assert client.post("/auth/register", json={"email": "f@example.com", "password": "password1",
                                               "role": "admin"}).status_code == 422


def test_forged_cookie_is_anonymous_and_api_key_wins(client):
    client.cookies.set("rag_session", "YWRtaW5AZXhhbXBsZS5jb20=|9999999999|deadbeef")
    assert client.get("/whoami").json()["via"] == "anonymous"
    client.cookies.clear()
    client.post("/auth/register", json={"email": "g@example.com", "password": "password1"})
    me = client.get("/whoami", headers={"X-API-Key": "k1"}).json()
    assert (me["user_id"], me["via"]) == ("bob", "api_key")


def test_auth_endpoints_require_json(client):
    r = client.post("/auth/login", content="email=a&password=b",
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code in (415, 422)
