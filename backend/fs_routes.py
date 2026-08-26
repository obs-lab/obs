from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import fs_access
import llm_bridge
from auth_routes import current_user

router = APIRouter(prefix="/api/fs", tags=["filesystem"])

ANALYZE_MAX_CHARS = 12000

_ANALYZE_SYSTEM = {
    "it": (
        "Analizzi il contenuto di un file che si trova sul computer dell'utente. "
        "Il file non e' stato caricato nell'archivio di OBS e non e' indicizzato. "
        "Rispondi solo con quello che il testo fornito consente di affermare. "
        "Se il testo e' troncato o insufficiente, dichiaralo."
    ),
    "en": (
        "You analyse the content of a file located on the user machine. "
        "The file has not been uploaded to the OBS archive and is not indexed. "
        "Answer only with what the provided text supports. "
        "If the text is truncated or insufficient, say so."
    ),
}


class RootRequest(BaseModel):
    path: str
    label: str = ""
    user_id: Optional[int] = None


class PathRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    path: Optional[str] = None
    pattern: str = "*"
    contains: str = ""
    max_results: int = 200


class AnalyzeRequest(BaseModel):
    path: str
    question: str = ""
    lang: str = "it"


@router.get("/status")
def fs_status(user: dict = Depends(current_user)):
    out = fs_access.status(user)
    out["llm_available"] = llm_bridge.available()
    out["llm_label"] = llm_bridge.label()
    return out


@router.get("/roots")
def fs_roots(user: dict = Depends(current_user)):
    if not fs_access.FS_ENABLED:
        raise HTTPException(status_code=403, detail="Il pannello filesystem e' disattivato.")
    return {"roots": fs_access.list_roots(user)}


@router.post("/roots")
def fs_add_root(req: RootRequest, user: dict = Depends(current_user)):
    try:
        return fs_access.add_root(user, req.path, req.label, req.user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/roots/{root_id}")
def fs_remove_root(root_id: str, user: dict = Depends(current_user)):
    try:
        fs_access.remove_root(user, root_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.get("/browse")
def fs_browse(path: Optional[str] = None, user: dict = Depends(current_user)):
    try:
        return fs_access.browse(user, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/read")
def fs_read(req: PathRequest, user: dict = Depends(current_user)):
    try:
        return fs_access.read_file(user, req.path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Lettura fallita: " + str(exc))


@router.post("/search")
def fs_search(req: SearchRequest, user: dict = Depends(current_user)):
    try:
        return fs_access.search(
            user, req.path, req.pattern, req.contains, min(req.max_results, 500)
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/analyze")
def fs_analyze(req: AnalyzeRequest, user: dict = Depends(current_user)):
    try:
        payload = fs_access.read_file(user, req.path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    text = payload["text"][:ANALYZE_MAX_CHARS]
    truncated = payload["truncated"] or len(payload["text"]) > ANALYZE_MAX_CHARS

    if not llm_bridge.available():
        return {
            "path": payload["path"],
            "name": payload["name"],
            "answer": "",
            "text": text,
            "truncated": truncated,
            "llm_available": False,
            "note": "Nessun motore linguistico attivo: il file e' stato letto ma non interpretato.",
        }

    lang = "en" if req.lang == "en" else "it"
    question = req.question.strip() or (
        "Riassumi il contenuto del file e indica cosa contiene."
        if lang == "it" else
        "Summarise the file content and state what it contains."
    )
    message = (
        "FILE: " + payload["name"] + "\n"
        "PERCORSO: " + payload["path"] + "\n\n"
        "CONTENUTO:\n" + text + "\n\n"
        "RICHIESTA: " + question
    )
    try:
        answer = llm_bridge.complete(_ANALYZE_SYSTEM[lang], message, 1400)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Analisi fallita: " + str(exc))

    return {
        "path": payload["path"],
        "name": payload["name"],
        "answer": answer,
        "text": text,
        "truncated": truncated,
        "llm_available": True,
        "note": "",
    }
