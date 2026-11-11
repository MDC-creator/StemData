"""The real login flow (no overrides of current_user), against an in-memory database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from stemchub import auth
from stemchub.api import app
from stemchub.config import Settings
from stemchub.db import Base, get_session
from stemchub.models import AuthSession, User

H = {"X-Requested-With": "stemchub"}


@pytest.fixture
def db_session(monkeypatch):
    monkeypatch.setattr(auth, "FAIL_DELAY_S", 0)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        for name, role in (("anna", "admin"), ("sam", "scientist"), ("vic", "viewer")):
            s.add(User(username=name, password_hash=auth.hash_password(f"{name}-password-1"), role=role))
        s.commit()

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = override
    yield Session
    app.dependency_overrides.clear()


def client_for(user: str | None = None) -> TestClient:
    c = TestClient(app, headers=H)
    if user:
        r = c.post("/api/auth/login", json={"username": user, "password": f"{user}-password-1"})
        assert r.status_code == 200, r.text
    return c


def test_password_hashing():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong", h)
    assert auth.hash_password("same") != auth.hash_password("same")  # salted
    assert not auth.verify_password("x", "garbage")


def test_password_rules():
    with pytest.raises(ValueError, match="at least"):
        auth.check_password_rules("short")
    with pytest.raises(ValueError, match="user name"):
        auth.check_password_rules("dhia-is-great", "dhia")


def test_everything_needs_a_login(db_session):
    c = client_for()
    for path in ("/api/runs", "/api/summary", "/api/health", "/api/jobs", "/api/auth/me"):
        assert c.get(path).status_code == 401, path


def test_login_sets_an_httponly_cookie_and_me_works(db_session):
    c = TestClient(app, headers=H)
    r = c.post("/api/auth/login", json={"username": " SAM ", "password": "sam-password-1"})
    assert r.status_code == 200 and r.json()["role"] == "scientist"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").json()["username"] == "sam"
    assert c.get("/api/runs").status_code == 200
    with db_session() as s:  # only a hash of the token is stored
        stored = s.query(AuthSession).one().token_hash
    assert stored not in r.headers["set-cookie"]


def test_wrong_password_does_not_reveal_whether_the_user_exists(db_session):
    c = TestClient(app, headers=H)
    a = c.post("/api/auth/login", json={"username": "sam", "password": "nope-nope-nope"})
    b = c.post("/api/auth/login", json={"username": "nobody", "password": "nope-nope-nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_lockout_after_five_wrong_passwords(db_session):
    c = TestClient(app, headers=H)
    for _ in range(auth.MAX_FAILED):
        c.post("/api/auth/login", json={"username": "vic", "password": "wrong-wrong-1"})
    r = c.post("/api/auth/login", json={"username": "vic", "password": "vic-password-1"})  # even the right one
    assert r.status_code == 401 and "Too many" in r.json()["detail"]


def test_roles(db_session):
    viewer, scientist = client_for("vic"), client_for("sam")
    assert viewer.get("/api/runs").status_code == 200
    assert viewer.post("/api/sync").status_code == 403
    assert viewer.post("/api/uploads/process", data={"run_id": "U1"}, files={"file": ("p.csv", b"x")}).status_code == 403
    assert scientist.get("/api/users").status_code == 403


def test_requests_that_change_data_need_the_header(db_session):
    c = client_for("anna")
    assert c.post("/api/sync", headers={"X-Requested-With": ""}).status_code == 403
    r = TestClient(app).post("/api/auth/login", json={"username": "anna", "password": "anna-password-1"})
    assert r.status_code == 403  # a cross-site form cannot set this header


def test_logout_ends_the_session(db_session):
    c = client_for("sam")
    token = c.cookies.get(auth.COOKIE)
    assert c.post("/api/auth/logout").status_code == 204
    c2 = TestClient(app, headers=H, cookies={auth.COOKIE: token})  # an old copy of the cookie is useless
    assert c2.get("/api/auth/me").status_code == 401


def test_admin_manages_users_and_cannot_lock_themselves_out(db_session):
    admin = client_for("anna")
    r = admin.post("/api/users", json={"username": "Lea", "password": "tulip-garden-12", "role": "scientist"})
    assert r.status_code == 201 and r.json()["username"] == "lea"
    assert admin.post("/api/users", json={"username": "lea", "password": "another-one-12"}).status_code == 409
    assert admin.post("/api/users", json={"username": "kim", "password": "short"}).status_code == 422
    assert admin.post("/api/users", json={"username": "kim", "password": "long-enough-1", "role": "boss"}).status_code == 422

    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"active": False}).status_code == 409
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 409

    lea = client_for()
    assert lea.post("/api/auth/login", json={"username": "lea", "password": "tulip-garden-12"}).status_code == 200
    lea_id = r.json()["id"]
    assert admin.patch(f"/api/users/{lea_id}", json={"active": False}).status_code == 200
    assert lea.get("/api/auth/me").status_code == 401  # deactivating logs out everywhere


def test_change_own_password(db_session):
    c = client_for("sam")
    bad = c.post("/api/auth/password", json={"current_password": "wrong", "new_password": "new-secret-123"})
    assert bad.status_code == 403
    assert (
        c.post("/api/auth/password", json={"current_password": "sam-password-1", "new_password": "new-secret-123"}).status_code
        == 204
    )
    fresh = TestClient(app, headers=H)
    assert fresh.post("/api/auth/login", json={"username": "sam", "password": "new-secret-123"}).status_code == 200


def test_first_admin_is_created_once_from_settings(db_session):
    with db_session() as s:
        s.query(AuthSession).delete()
        s.query(User).delete()
        s.commit()
        auth.bootstrap_admin(s, Settings(admin_username="Boss", admin_password="harbor-light-123"))
        auth.bootstrap_admin(s, Settings(admin_username="other", admin_password="other-secret-123"))
        users = s.query(User).all()
    assert [(u.username, u.role) for u in users] == [("boss", "admin")]


def test_simple_passwords_only_when_allowed(monkeypatch):
    with pytest.raises(ValueError):
        auth.check_password_rules("root", "root")  # default: strict
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(allow_simple_passwords=True))
    auth.check_password_rules("root", "root")  # local test mode: allowed
    with pytest.raises(ValueError, match="empty"):
        auth.check_password_rules("", "root")
