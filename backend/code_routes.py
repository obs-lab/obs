import io
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

import auth
import code_clients
import code_files
import code_store
import runners
from auth_routes import current_user, require_roles

router = APIRouter(prefix="/api/code", tags=["code"])


class RunRequest(BaseModel):
    language: str
    source: str
    stdin: str = ""
    with_obs: bool = True


class SaveRequest(BaseModel):
    name: str
    language: str
    source: str
    script_id: Optional[str] = None


class ExportRequest(BaseModel):
    name: str
    language: str
    source: str
    with_obs: bool = True


@router.get("/status")
def code_status(user: dict = Depends(current_user)):
    return runners.runner_status()


class ImageRequest(BaseModel):
    language: str


@router.post("/images/pull")
def code_image_pull(
    req: ImageRequest,
    user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN)),
):
    result = runners.pull_image(req.language)
    if not result.get("started"):
        raise HTTPException(status_code=400, detail=result.get("error", "avvio fallito"))
    return result


@router.get("/images/pull/status")
def code_image_pull_status(
    language: str = "",
    user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN)),
):
    return runners.pull_status(language)


@router.delete("/images/{language}")
def code_image_remove(
    language: str,
    user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN)),
):
    result = runners.remove_image(language)
    if not result.get("removed"):
        raise HTTPException(status_code=400, detail=result.get("error", "rimozione fallita"))
    return result


@router.post("/images/cleanup")
def code_cleanup(
    user: dict = Depends(require_roles(auth.ROLE_DEVELOPER, auth.ROLE_ADMIN)),
):
    result = runners.cleanup()
    if not result.get("cleaned"):
        raise HTTPException(status_code=400, detail=result.get("error", "pulizia fallita"))
    return result


@router.post("/run")
def code_run(req: RunRequest, user: dict = Depends(current_user)):
    if req.language not in runners.LANGUAGES:
        raise HTTPException(status_code=400, detail="Linguaggio non supportato.")

    code_store.purge_expired_tokens()

    token = ""
    client = ""
    if req.with_obs:
        token = code_store.create_ephemeral_token(user["user_id"])
        client = code_clients.CLIENTS.get(req.language, "")

    try:
        result = runners.execute(
            language_key=req.language,
            source=req.source,
            token=token,
            stdin=req.stdin,
            client_source=client,
            user_id=user["user_id"],
        )
    finally:
        if token:
            code_store.revoke_ephemeral_token(token)

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration": round(result.duration, 3),
        "timed_out": result.timed_out,
        "stage": result.stage,
        "plots": result.plots,
        "specs": result.specs,
    }


@router.get("/files")
def code_files_list(user: dict = Depends(current_user)):
    return {
        "files": code_files.list_files(user["user_id"]),
        "usage": code_files.usage(user["user_id"]),
    }


@router.post("/files")
async def code_files_upload(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    content = await file.read()
    try:
        saved = code_files.save_file(user["user_id"], file.filename, content)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "file": saved,
        "usage": code_files.usage(user["user_id"]),
    }


class FileContent(BaseModel):
    content: str


@router.get("/files/{name}/content")
def code_files_content(name: str, user: dict = Depends(current_user)):
    try:
        return code_files.read_text(user["user_id"], name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/files/{name}/content")
def code_files_save_content(
    name: str,
    req: FileContent,
    user: dict = Depends(current_user),
):
    try:
        saved = code_files.write_text(user["user_id"], name, req.content)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"file": saved, "usage": code_files.usage(user["user_id"])}


@router.get("/files/{name}")
def code_files_download(name: str, user: dict = Depends(current_user)):
    try:
        data = code_files.read_file(user["user_id"], name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.delete("/files/{name}")
def code_files_delete(name: str, user: dict = Depends(current_user)):
    try:
        code_files.delete_file(user["user_id"], name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "deleted": name,
        "usage": code_files.usage(user["user_id"]),
    }


@router.post("/files/clear")
def code_files_clear(user: dict = Depends(current_user)):
    n = code_files.clear_files(user["user_id"])
    return {"deleted": n, "usage": code_files.usage(user["user_id"])}


@router.get("/scripts")
def code_list(user: dict = Depends(current_user)):
    return code_store.list_scripts(user["user_id"])


@router.get("/scripts/{script_id}")
def code_get(script_id: str, user: dict = Depends(current_user)):
    try:
        return code_store.get_script(user["user_id"], script_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scripts")
def code_save(req: SaveRequest, user: dict = Depends(current_user)):
    if req.language not in runners.LANGUAGES and req.language not in runners.BROWSER_LANGUAGES:
        raise HTTPException(status_code=400, detail="Linguaggio non supportato.")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Nome mancante.")
    try:
        return code_store.save_script(
            owner_id=user["user_id"],
            name=req.name.strip(),
            language=req.language,
            source=req.source,
            script_id=req.script_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/scripts/{script_id}")
def code_delete(script_id: str, user: dict = Depends(current_user)):
    try:
        code_store.delete_script(user["user_id"], script_id)
        return {"deleted": script_id}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _readme(language: str, with_obs: bool) -> str:
    lang = runners.LANGUAGES.get(language)
    if lang is None:
        return "Script esportato da OBS.\n"

    lines = [
        "Script esportato da OBS",
        "=======================",
        "",
        f"Linguaggio: {lang.label}",
        f"File sorgente: {lang.source_name}",
        "",
    ]

    if with_obs and lang.client_file:
        lines += [
            "Questo script usa la libreria client OBS inclusa "
            f"({lang.client_file}).",
            "Per farlo funzionare fuori da OBS servono due variabili d'ambiente:",
            "",
            "  OBS_URL    indirizzo del server OBS, esempio http://localhost:8000",
            "  OBS_TOKEN  token di sessione valido",
            "",
            "Il token di sessione si ottiene facendo login su OBS e leggendo il",
            "cookie obs_session, oppure chiamando POST /api/auth/login.",
            "",
            "Su Linux e macOS:",
            "  export OBS_URL=http://localhost:8000",
            "  export OBS_TOKEN=il_tuo_token",
            "",
            "Su Windows (PowerShell):",
            "  $env:OBS_URL=\"http://localhost:8000\"",
            "  $env:OBS_TOKEN=\"il_tuo_token\"",
            "",
            "Se rimuovi le chiamate alla libreria, lo script gira in autonomia",
            "senza bisogno di OBS.",
            "",
        ]
    else:
        lines += [
            "Questo script non dipende da OBS e gira in autonomia.",
            "",
        ]

    lines += ["Esecuzione:", ""]
    if lang.local_build_cmd:
        lines.append("  " + " ".join(lang.local_build_cmd))
    lines.append("  " + " ".join(lang.local_cmd))
    lines.append("")

    return "\n".join(lines)


@router.post("/export")
def code_export(req: ExportRequest, user: dict = Depends(current_user)):
    lang = runners.LANGUAGES.get(req.language)
    if lang is None:
        raise HTTPException(status_code=400, detail="Linguaggio non supportato.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(lang.source_name, req.source)
        if req.with_obs and lang.client_file:
            zf.writestr(lang.client_file, code_clients.CLIENTS.get(req.language, ""))
        zf.writestr("README.txt", _readme(req.language, req.with_obs))

    buffer.seek(0)
    safe = "".join(c for c in req.name if c.isalnum() or c in "-_") or "script"

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )
