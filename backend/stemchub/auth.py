"""Login: users with hashed passwords, server-side sessions in an HttpOnly cookie, three roles.

- Passwords: scrypt (Python standard library), random salt per user; never stored or logged in clear.
- Sessions: a random token in an HttpOnly, SameSite=Lax cookie; the database keeps only its SHA-256,
  so a leaked database does not leak logins. Logging out deletes the session.
- Brute force: 5 wrong passwords lock the account for 5 minutes; every failure is slowed down.
- Roles: viewer (read) < scientist (also upload, re-run analysis, sync) < admin (also manage users).
"""

import base64
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from stemchub.config import Settings, get_settings
from stemchub.db import get_session
from stemchub.models import AuthSession, User

COOKIE = "stemchub_session"
ROLES = ("viewer", "scientist", "admin")
MIN_PASSWORD = 10
MAX_FAILED = 5
LOCK_MINUTES = 5
FAIL_DELAY_S = 0.5  # slows down guessing; tests set it to 0

_N, _R, _P = 2**14, 8, 1  # scrypt cost (about 50 ms, 16 MB per hash)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def check_password_rules(password: str, username: str = "") -> None:
    if get_settings().allow_simple_passwords:  # local test installations only (e.g. root / root)
        if not password:
            raise ValueError("Password must not be empty.")
        return
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Password must have at least {MIN_PASSWORD} characters.")
    if username and username.lower() in password.lower():
        raise ValueError("Password must not contain the user name.")


def check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    return role


def normalize_username(username: str) -> str:
    name = (username or "").strip().lower()
    if not (2 <= len(name) <= 64) or not all(c.isalnum() or c in "._-@" for c in name):
        raise ValueError("User name: 2–64 letters, digits or . _ - @")
    return name


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (tests) returns naive datetimes; PostgreSQL returns aware ones."""
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- login / sessions


class LoginFailed(Exception):
    pass


def authenticate(db: Session, username: str, password: str) -> User:
    """Returns the user or raises LoginFailed with a message that does not reveal whether the user exists."""
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.username == (username or "").strip().lower()))
    if user is not None and user.locked_until and _aware(user.locked_until) > now:
        raise LoginFailed(f"Too many wrong passwords. Try again after {_aware(user.locked_until):%H:%M} UTC.")
    if user is None or not user.active or not verify_password(password or "", user.password_hash):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED:
                user.failed_logins, user.locked_until = 0, now + timedelta(minutes=LOCK_MINUTES)
            db.commit()
        time.sleep(FAIL_DELAY_S)
        raise LoginFailed("Wrong user name or password.")
    user.failed_logins, user.locked_until, user.last_login = 0, None, now
    db.commit()
    return user


def create_session(db: Session, user: User, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))  # tidy up old ones
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, expires_at=now + timedelta(hours=hours)))
    db.commit()
    return token


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        db.commit()


def end_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


# ---------------------------------------------------------------- FastAPI dependencies


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    token = request.cookies.get(COOKIE)
    if token:
        s = db.get(AuthSession, _token_hash(token))
        if s is not None and _aware(s.expires_at) > datetime.now(UTC):
            user = db.get(User, s.user_id)
            if user is not None and user.active:
                return user
    raise HTTPException(401, "Please log in.")


def _requires(minimum: str):
    level = ROLES.index(minimum)

    def dependency(user: User = Depends(current_user)) -> User:
        if ROLES.index(user.role) < level:
            raise HTTPException(403, f"This needs the role '{minimum}'.")
        return user

    return dependency


# built once, so tests can override `current_user` and every role check follows
require_scientist = _requires("scientist")
require_admin = _requires("admin")


def bootstrap_admin(db: Session, settings: Settings | None = None) -> None:
    """First start: create the admin from ADMIN_USERNAME / ADMIN_PASSWORD if there is no user at all."""
    settings = settings or get_settings()
    if not settings.admin_username or not settings.admin_password:
        return
    if db.scalar(select(func.count()).select_from(User)):
        return
    name = normalize_username(settings.admin_username)
    check_password_rules(settings.admin_password, name)
    db.add(User(username=name, password_hash=hash_password(settings.admin_password), role="admin"))
    db.commit()
