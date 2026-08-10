from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import sharing
from auth_routes import current_user

router = APIRouter(prefix="/api/sharing", tags=["sharing"])

_ownership_check = None


def register_ownership_check(fn) -> None:
    """main registra qui il predicato (target_type, target_id, user_id) -> bool.
    Serve a evitare un import circolare fra sharing_routes e main."""
    global _ownership_check
    _ownership_check = fn


def _assert_recipient_visible(actor: dict, user_id: int) -> None:
    target = auth.get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Utente destinatario non trovato.")
    if actor["role"] == auth.ROLE_DEVELOPER:
        return
    if target["azienda"] != actor["azienda"]:
        raise HTTPException(403, "Puoi condividere solo con utenti della tua azienda.")


class GroupCreate(BaseModel):
    name: str


class GroupRename(BaseModel):
    name: str


class MemberRequest(BaseModel):
    user_id: int


class ShareCreate(BaseModel):
    target_type: str
    target_id: str
    recipient_type: str
    recipient_id: int


@router.get("/collaborators")
def collaborators(user: dict = Depends(current_user)):
    people = auth.list_users(user["role"], user["azienda"])
    out = []
    for p in people:
        if p["id"] == user["user_id"]:
            continue
        out.append({"id": p["id"], "username": p["username"],
                    "email": p["email"], "azienda": p.get("azienda", "")})
    return out


@router.get("/groups")
def groups(user: dict = Depends(current_user)):
    return sharing.list_groups(user["user_id"])


@router.post("/groups")
def create_group(req: GroupCreate, user: dict = Depends(current_user)):
    try:
        return sharing.create_group(user["user_id"], req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/groups/{group_id}")
def rename_group(group_id: int, req: GroupRename, user: dict = Depends(current_user)):
    try:
        return sharing.rename_group(user["user_id"], group_id, req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, user: dict = Depends(current_user)):
    try:
        sharing.delete_group(user["user_id"], group_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@router.post("/groups/{group_id}/members")
def add_member(group_id: int, req: MemberRequest, user: dict = Depends(current_user)):
    _assert_recipient_visible(user, req.user_id)
    try:
        sharing.add_member(user["user_id"], group_id, req.user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@router.delete("/groups/{group_id}/members/{member_id}")
def remove_member(group_id: int, member_id: int, user: dict = Depends(current_user)):
    try:
        sharing.remove_member(user["user_id"], group_id, member_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@router.get("/shares")
def my_shares(user: dict = Depends(current_user)):
    return sharing.list_shares_by_owner(user["user_id"])


@router.post("/shares")
def create_share(req: ShareCreate, user: dict = Depends(current_user)):
    if req.recipient_type == sharing.RECIPIENT_USER:
        _assert_recipient_visible(user, req.recipient_id)
    check = None
    if _ownership_check is not None and user["role"] != auth.ROLE_DEVELOPER:
        check = _ownership_check
    try:
        res = sharing.create_share(user["user_id"], req.target_type, req.target_id,
                                   req.recipient_type, req.recipient_id,
                                   is_owner=check)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, **res}


@router.delete("/shares/{share_id}")
def revoke_share(share_id: int, user: dict = Depends(current_user)):
    try:
        sharing.revoke_share(user["user_id"], share_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}