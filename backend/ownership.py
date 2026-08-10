from typing import Optional

import auth

UNASSIGNED = None


def visible_owner_ids(user: dict) -> Optional[set]:
    if user["role"] == auth.ROLE_DEVELOPER:
        return None
    if user["role"] == auth.ROLE_ADMIN:
        company_users = auth.list_users(user["role"], user["azienda"])
        ids = {u["id"] for u in company_users}
        ids.add(user["user_id"])
        return ids
    return {user["user_id"]}


def can_see_item(user: dict, owner_id, extra_doc_ids=None, doc_id=None) -> bool:
    if user["role"] == auth.ROLE_DEVELOPER:
        return True
    if extra_doc_ids and doc_id is not None and doc_id in extra_doc_ids:
        return True
    allowed = visible_owner_ids(user)
    if owner_id is None:
        return False
    return owner_id in allowed


def filter_chunks(user: dict, chunks: list, extra_doc_ids=None) -> list:
    if user["role"] == auth.ROLE_DEVELOPER:
        return chunks
    allowed = visible_owner_ids(user)
    extra = extra_doc_ids or set()
    out = []
    for c in chunks:
        oid = c.get("owner_id")
        if oid is not None and oid in allowed:
            out.append(c)
        elif c.get("doc_id") in extra:
            out.append(c)
    return out


def filter_documents(user: dict, docs: list, extra_doc_ids=None) -> list:
    if user["role"] == auth.ROLE_DEVELOPER:
        return docs
    allowed = visible_owner_ids(user)
    extra = extra_doc_ids or set()
    out = []
    for d in docs:
        oid = d.get("owner_id")
        if oid is not None and oid in allowed:
            out.append(d)
        elif d.get("doc_id") in extra:
            out.append(d)
    return out


def filter_images(user: dict, images: list, extra_doc_ids=None) -> list:
    if user["role"] == auth.ROLE_DEVELOPER:
        return images
    allowed = visible_owner_ids(user)
    extra = extra_doc_ids or set()
    out = []
    for im in images:
        oid = im.get("owner_id")
        if oid is not None and oid in allowed:
            out.append(im)
        elif im.get("img_id") in extra:
            out.append(im)
    return out
