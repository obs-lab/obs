from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

import auth
import sharing

SESSION_COOKIE = "obs_session"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=auth.SESSION_IDLE_HOURS * 3600,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE) or _bearer_token(request)
    user = auth.validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sessione non valida o scaduta.")
    return user


def require_roles(*roles):
    def checker(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Permessi insufficienti.")
        return user
    return checker


def can_manage(actor: dict, target: dict) -> bool:
    if actor["role"] == auth.ROLE_DEVELOPER:
        return True
    if actor["role"] == auth.ROLE_ADMIN:
        if target["role"] == auth.ROLE_DEVELOPER:
            return False
        return target["azienda"] == actor["azienda"]
    return False


router = APIRouter(prefix="/api/auth", tags=["auth"])


_user_cleanup = None


def register_user_cleanup(fn) -> None:
    """main registra qui la pulizia degli oggetti in memoria appartenuti a un
    utente cancellato. Evita l'import circolare fra auth_routes e main."""
    global _user_cleanup
    _user_cleanup = fn



class LoginRequest(BaseModel):
    email: str
    password: str


class SetupRequest(BaseModel):
    email: str
    username: str = "Developer"
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    email: str
    username: str
    password: str
    role: str = auth.ROLE_USER
    azienda: str = ""


class ResetPasswordRequest(BaseModel):
    user_id: int
    temp_password: str


class RoleRequest(BaseModel):
    user_id: int
    role: str


class ActiveRequest(BaseModel):
    user_id: int
    active: bool


class UserIdRequest(BaseModel):
    user_id: int


class UpdateUserRequest(BaseModel):
    user_id: Optional[int] = None
    email: Optional[str] = None
    username: Optional[str] = None
    azienda: Optional[str] = None
    initials: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None


@router.post("/login")
def login(req: LoginRequest, response: Response):
    try:
        session = auth.authenticate(req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    _set_session_cookie(response, session["token"])
    return {
        "email":          session["email"],
        "username":       session["username"],
        "role":           session["role"],
        "azienda":        session["azienda"],
        "must_change_pw": session["must_change_pw"],
    }


@router.get("/setup-status")
def setup_status():
    return {"needs_setup": auth.count_users() == 0}


@router.post("/setup")
def setup(req: SetupRequest, response: Response):
    if auth.count_users() > 0:
        raise HTTPException(status_code=409, detail="Setup already completed.")
    try:
        auth.create_user(req.email, req.username, req.password,
                         role=auth.ROLE_DEVELOPER, must_change_pw=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        session = auth.authenticate(req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    _set_session_cookie(response, session["token"])
    return {
        "email":          session["email"],
        "username":       session["username"],
        "role":           session["role"],
        "azienda":        session["azienda"],
        "must_change_pw": session["must_change_pw"],
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    auth.destroy_session(token)
    _clear_session_cookie(response)
    return {"success": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, response: Response,
                    user: dict = Depends(current_user)):
    try:
        auth.change_password(user["user_id"], req.old_password, req.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _clear_session_cookie(response)
    return {"success": True, "relogin": True}


@router.post("/users/update")
def update_user(req: UpdateUserRequest, user: dict = Depends(current_user)):
    target_id = req.user_id if req.user_id is not None else user["user_id"]
    is_self = target_id == user["user_id"]

    if not is_self:
        target = auth.get_user_by_id(target_id)
        if not target:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        if not can_manage(user, target):
            raise HTTPException(status_code=403, detail="Non hai i permessi per modificare questo utente.")

    fields = {
        "email":    req.email,
        "username": req.username,
        "azienda":  req.azienda,
        "initials": req.initials,
        "role":     req.role,
        "active":   req.active,
    }
    try:
        updated = auth.update_user(user["user_id"], user["role"], target_id, fields)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "user": {
        "id": updated["id"], "email": updated["email"],
        "username": updated["username"], "azienda": updated["azienda"],
        "role": updated["role"], "initials": updated.get("initials", ""),
    }}


@router.get("/users")
def list_users(user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    return auth.list_users(user["role"], user["azienda"])


@router.post("/users")
def create_user(req: CreateUserRequest,
                user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    if user["role"] == auth.ROLE_ADMIN:
        if req.role in (auth.ROLE_DEVELOPER, auth.ROLE_ADMIN):
            raise HTTPException(status_code=403, detail="Un admin puo' creare solo utenti standard.")
        forced_azienda = user["azienda"]
    else:
        forced_azienda = req.azienda
    try:
        new_user = auth.create_user(
            email=req.email, username=req.username, password=req.password,
            role=req.role, azienda=forced_azienda, must_change_pw=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "user": new_user}


@router.post("/users/reset-password")
def reset_password(req: ResetPasswordRequest,
                   user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    target = auth.get_user_by_id(req.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    if not can_manage(user, target):
        raise HTTPException(status_code=403, detail="Non puoi gestire questo utente.")
    try:
        auth.reset_password(req.user_id, req.temp_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.post("/users/unlock")
def unlock_user(req: UserIdRequest,
                user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    target = auth.get_user_by_id(req.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    if not can_manage(user, target):
        raise HTTPException(status_code=403, detail="Non puoi gestire questo utente.")
    auth.unlock_user(req.user_id)
    return {"success": True}


@router.post("/users/set-active")
def set_active(req: ActiveRequest,
               user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    target = auth.get_user_by_id(req.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    if not can_manage(user, target):
        raise HTTPException(status_code=403, detail="Non puoi gestire questo utente.")
    if target["id"] == user["user_id"] and not req.active:
        raise HTTPException(status_code=400, detail="Non puoi disattivare te stesso.")
    auth.set_user_active(req.user_id, req.active)
    return {"success": True}


@router.post("/users/set-role")
def set_role(req: RoleRequest,
             user: dict = Depends(require_roles(auth.ROLE_DEVELOPER))):
    target = auth.get_user_by_id(req.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    try:
        auth.set_user_role(req.user_id, req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.post("/users/delete")
def delete_user(req: UserIdRequest,
                user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    target = auth.get_user_by_id(req.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    if not can_manage(user, target):
        raise HTTPException(status_code=403, detail="Non puoi gestire questo utente.")
    if target["id"] == user["user_id"]:
        raise HTTPException(status_code=400, detail="Non puoi eliminare te stesso.")
    try:
        auth.delete_user(req.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    purged = sharing.purge_user(req.user_id)
    orphans = None
    if _user_cleanup is not None:
        try:
            orphans = _user_cleanup(req.user_id)
        except Exception:
            orphans = None
    auth.destroy_all_sessions(req.user_id)
    return {"success": True, "purged": purged, "orphans": orphans}


@router.get("/access-log")
def access_log(limit: int = 100,
               user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN))):
    entries = auth.read_access_log(limit)
    if user["role"] == auth.ROLE_ADMIN:
        emails = {u["email"] for u in auth.list_users(user["role"], user["azienda"])}
        entries = [e for e in entries if e.get("email") in emails]
    return entries
