"""Endpoints for login, logout, the own account, and (admins only) user management."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from stemchub import auth
from stemchub.config import Settings, get_settings
from stemchub.db import get_session
from stemchub.models import User
from stemchub.schemas import UserOut

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = None


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    try:
        user = auth.authenticate(db, body.username, body.password)
    except auth.LoginFailed as exc:
        raise HTTPException(401, str(exc)) from None
    token = auth.create_session(db, user, settings.session_hours)
    response.set_cookie(
        auth.COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,  # JavaScript cannot read it
        samesite="lax",  # not sent with cross-site POSTs
        secure=settings.cookie_secure,
        path="/",
    )
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_session)):
    auth.end_session(db, request.cookies.get(auth.COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(auth.COOKIE, path="/")
    return response


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(auth.current_user)):
    return user


@router.post("/auth/password", status_code=204)
def change_own_password(body: PasswordChange, user: User = Depends(auth.current_user), db: Session = Depends(get_session)):
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Current password is wrong.")
    try:
        auth.check_password_rules(body.new_password, user.username)
    except ValueError as exc:
        raise _bad(exc) from None
    user.password_hash = auth.hash_password(body.new_password)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- admin: users


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(auth.require_admin)])
def list_users(db: Session = Depends(get_session)):
    return db.scalars(select(User).order_by(User.username)).all()


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(auth.require_admin)])
def create_user(body: UserCreate, db: Session = Depends(get_session)):
    try:
        name = auth.normalize_username(body.username)
        auth.check_role(body.role)
        auth.check_password_rules(body.password, name)
    except ValueError as exc:
        raise _bad(exc) from None
    if db.scalar(select(User).where(User.username == name)):
        raise HTTPException(409, f"User '{name}' already exists.")
    user = User(username=name, password_hash=auth.hash_password(body.password), role=body.role)
    db.add(user)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserPatch, admin: User = Depends(auth.require_admin), db: Session = Depends(get_session)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    if user.id == admin.id and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(409, "You cannot deactivate yourself or remove your own admin role.")
    try:
        if body.role is not None:
            user.role = auth.check_role(body.role)
        if body.password is not None:
            auth.check_password_rules(body.password, user.username)
            user.password_hash = auth.hash_password(body.password)
            user.failed_logins, user.locked_until = 0, None
            auth.end_all_sessions(db, user.id)  # a reset password logs the user out everywhere
        if body.active is not None:
            user.active = body.active
            if not body.active:
                auth.end_all_sessions(db, user.id)
    except ValueError as exc:
        db.rollback()
        raise _bad(exc) from None
    db.commit()
    return user
