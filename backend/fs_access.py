import fnmatch
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import auth
import ownership

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
FS_DB = DATA_DIR / "filesystem.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

FS_ENABLED = os.environ.get("OBS_FS_ENABLED", "1").strip() == "1"
FS_SERVER_MODE = os.environ.get("OBS_FS_SERVER_MODE", "0").strip() == "1"
FS_MAX_READ_BYTES = int(os.environ.get("OBS_FS_MAX_READ_BYTES", str(4 * 1024 * 1024)))
FS_MAX_TEXT_CHARS = int(os.environ.get("OBS_FS_MAX_TEXT_CHARS", "200000"))
FS_MAX_ENTRIES = int(os.environ.get("OBS_FS_MAX_ENTRIES", "2000"))
FS_MAX_SCAN_FILES = int(os.environ.get("OBS_FS_MAX_SCAN", "20000"))
FS_MAX_DEPTH = int(os.environ.get("OBS_FS_MAX_DEPTH", "12"))
FS_SCAN_TIMEOUT = int(os.environ.get("OBS_FS_SCAN_TIMEOUT", "20"))

DENIED_SEGMENTS = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".config/gcloud",
    "node_modules", ".git", "__pycache__", ".venv", "venv",
}

DENIED_NAMES = {
    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "authorized_keys",
    "shadow", "passwd", "sudoers", "auth.db", "code.db", "agents.db",
    "filesystem.db", "sheets.db",
}

DENIED_PATTERNS = ("*.key", "*.pem", "*.pfx", "*.p12", "*.keystore", "*.jks")

DENIED_ROOTS = (
    "/etc", "/proc", "/sys", "/dev", "/boot", "/var/lib", "/root",
    "/System", "/private/etc", "/Library/Keychains",
    "C:\\Windows", "C:\\ProgramData", "C:\\Program Files",
)

TEXT_SUFFIXES = {
    "txt", "md", "markdown", "log", "csv", "tsv", "json", "yaml", "yml",
    "xml", "html", "htm", "ini", "cfg", "conf", "py", "js", "ts", "r",
    "m", "c", "h", "cpp", "hpp", "java", "sql", "sh", "bat", "tex", "rst",
}
DOC_SUFFIXES = {"pdf", "docx", "doc", "xlsx", "xls"}
IMAGE_SUFFIXES = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}


def _now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(FS_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fs_roots (
                root_id    TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                label      TEXT NOT NULL,
                path       TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fs_roots_user ON fs_roots (user_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _resolve(raw) -> Path:
    return Path(os.path.expanduser(str(raw))).resolve()


def _segments_denied(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    for seg in DENIED_SEGMENTS:
        if seg.lower() in parts:
            return True
    name = path.name.lower()
    if name in DENIED_NAMES:
        return True
    for pattern in DENIED_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _is_denied_root(path: Path) -> bool:
    text = str(path)
    for denied in DENIED_ROOTS:
        try:
            if text == denied or text.startswith(denied + os.sep):
                return True
        except Exception:
            continue
    if path == path.anchor and str(path) in ("/", "\\"):
        return True
    return False


def _overlaps_data_dir(path: Path) -> bool:
    data = DATA_DIR.resolve()
    try:
        path.relative_to(data)
        return True
    except ValueError:
        pass
    try:
        data.relative_to(path)
        return True
    except ValueError:
        return False


def validate_root(raw: str) -> Path:
    if not FS_ENABLED:
        raise PermissionError("Il pannello filesystem e' disattivato.")
    candidate = _resolve(raw)
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("Il percorso non esiste o non e' una cartella.")
    if _is_denied_root(candidate):
        raise PermissionError("Percorso di sistema non consentito.")
    if _overlaps_data_dir(candidate):
        raise PermissionError("La radice non puo' contenere o essere dentro i dati di OBS.")
    if _segments_denied(candidate):
        raise PermissionError("Percorso non consentito.")
    return candidate


def _target_user_allowed(actor: dict, target_user_id: int) -> bool:
    if actor["user_id"] == target_user_id:
        return True
    if not FS_SERVER_MODE:
        return False
    if actor["role"] == auth.ROLE_DEVELOPER:
        return True
    if actor["role"] == auth.ROLE_ADMIN:
        allowed = ownership.visible_owner_ids(actor)
        return allowed is None or target_user_id in allowed
    return False


def add_root(actor: dict, path: str, label: str = "",
             target_user_id: Optional[int] = None) -> dict:
    owner = actor["user_id"] if target_user_id is None else int(target_user_id)
    if not _target_user_allowed(actor, owner):
        raise PermissionError("Non puoi assegnare radici a questo utente.")
    resolved = validate_root(path)
    root_id = uuid.uuid4().hex
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT root_id FROM fs_roots WHERE user_id = ? AND path = ?",
            (owner, str(resolved)),
        ).fetchone()
        if existing is not None:
            raise ValueError("Radice gia' presente.")
        conn.execute(
            "INSERT INTO fs_roots (root_id, user_id, label, path, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (root_id, owner, (label or resolved.name)[:120], str(resolved),
             actor["user_id"], _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "root_id": root_id,
        "user_id": owner,
        "label": (label or resolved.name)[:120],
        "path": str(resolved),
    }


def list_roots(user: dict) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT root_id, user_id, label, path, created_at FROM fs_roots "
            "WHERE user_id = ? ORDER BY label",
            (user["user_id"],),
        ).fetchall()
        out = []
        for row in rows:
            entry = dict(row)
            entry["available"] = Path(entry["path"]).is_dir()
            out.append(entry)
        return out
    finally:
        conn.close()


def remove_root(actor: dict, root_id: str) -> None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT user_id FROM fs_roots WHERE root_id = ?", (root_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Radice non trovata.")
        if not _target_user_allowed(actor, row["user_id"]):
            raise PermissionError("Radice non accessibile.")
        conn.execute("DELETE FROM fs_roots WHERE root_id = ?", (root_id,))
        conn.commit()
    finally:
        conn.close()


def _root_paths(user: dict) -> list:
    return [Path(r["path"]) for r in list_roots(user) if Path(r["path"]).is_dir()]


def resolve_within_roots(user: dict, raw: str) -> Path:
    if not FS_ENABLED:
        raise PermissionError("Il pannello filesystem e' disattivato.")
    target = _resolve(raw)
    if _segments_denied(target):
        raise PermissionError("Percorso non consentito.")
    for root in _root_paths(user):
        try:
            target.relative_to(root)
            return target
        except ValueError:
            continue
    raise PermissionError("Percorso fuori dalle radici consentite.")


def _classify(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in DOC_SUFFIXES:
        return "document"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "binary"


def _entry(path: Path) -> dict:
    try:
        stat = path.stat()
        size = stat.st_size
        modified = stat.st_mtime
    except Exception:
        size = 0
        modified = 0.0
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": is_dir,
        "size": 0 if is_dir else size,
        "modified": modified,
        "kind": "dir" if is_dir else _classify(path),
        "readable": (not is_dir) and size <= FS_MAX_READ_BYTES,
    }


def browse(user: dict, raw: Optional[str] = None) -> dict:
    if raw is None or not str(raw).strip():
        roots = list_roots(user)
        return {
            "path": "",
            "parent": "",
            "is_root_list": True,
            "entries": [
                {
                    "name": r["label"],
                    "path": r["path"],
                    "is_dir": True,
                    "size": 0,
                    "modified": 0.0,
                    "kind": "dir",
                    "readable": False,
                }
                for r in roots if r["available"]
            ],
        }

    target = resolve_within_roots(user, raw)
    if not target.is_dir():
        raise ValueError("Il percorso non e' una cartella.")

    entries = []
    truncated = False
    try:
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if _segments_denied(child):
                continue
            entries.append(_entry(child))
            if len(entries) >= FS_MAX_ENTRIES:
                truncated = True
                break
    except PermissionError:
        raise PermissionError("Cartella non leggibile dal sistema operativo.")

    parent = ""
    if target.parent != target:
        try:
            resolve_within_roots(user, str(target.parent))
            parent = str(target.parent)
        except PermissionError:
            parent = ""

    return {
        "path": str(target),
        "parent": parent,
        "is_root_list": False,
        "truncated": truncated,
        "entries": entries,
    }


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:FS_MAX_TEXT_CHARS]


def _read_document(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        import fitz
        doc = fitz.open(str(path))
        return "\n".join(page.get_text() for page in doc)[:FS_MAX_TEXT_CHARS]
    if suffix in ("doc", "docx"):
        import docx
        document = docx.Document(str(path))
        return "\n".join(
            p.text for p in document.paragraphs if p.text.strip()
        )[:FS_MAX_TEXT_CHARS]
    if suffix in ("xlsx", "xls"):
        import pandas as pd
        frame = pd.read_excel(path)
        head = "Colonne: " + ", ".join(frame.columns.astype(str).tolist())
        return (head + "\nRighe: " + str(len(frame)) + "\n\n" +
                frame.to_string(index=False, max_rows=200))[:FS_MAX_TEXT_CHARS]
    raise ValueError("Formato non supportato per l'estrazione del testo.")


def read_file(user: dict, raw: str) -> dict:
    target = resolve_within_roots(user, raw)
    if not target.is_file():
        raise ValueError("Il percorso non e' un file.")
    size = target.stat().st_size
    if size > FS_MAX_READ_BYTES:
        raise ValueError(
            "File troppo grande: " + str(size) + " byte, limite " +
            str(FS_MAX_READ_BYTES) + "."
        )
    kind = _classify(target)
    if kind == "text":
        text = _read_text_file(target)
    elif kind == "document":
        text = _read_document(target)
    else:
        raise ValueError("Tipo di file non testuale.")
    return {
        "path": str(target),
        "name": target.name,
        "kind": kind,
        "size": size,
        "chars": len(text),
        "truncated": len(text) >= FS_MAX_TEXT_CHARS,
        "text": text,
    }


def search(user: dict, raw: Optional[str], pattern: str = "*",
           contains: str = "", max_results: int = 200) -> dict:
    roots = [resolve_within_roots(user, raw)] if raw else _root_paths(user)
    if not roots:
        return {"results": [], "scanned": 0, "truncated": False, "timed_out": False}

    needle = (contains or "").strip().lower()
    glob_pattern = pattern.strip() or "*"
    deadline = time.time() + FS_SCAN_TIMEOUT
    results = []
    scanned = 0
    timed_out = False

    for root in roots:
        base_depth = len(root.parts)
        for current, dirnames, filenames in os.walk(str(root)):
            if time.time() > deadline:
                timed_out = True
                break
            here = Path(current)
            if len(here.parts) - base_depth >= FS_MAX_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not _segments_denied(here / d)]
            for filename in filenames:
                path = here / filename
                if _segments_denied(path):
                    continue
                scanned += 1
                if scanned > FS_MAX_SCAN_FILES:
                    timed_out = True
                    break
                if not fnmatch.fnmatch(filename.lower(), glob_pattern.lower()):
                    continue
                if needle:
                    if _classify(path) != "text":
                        continue
                    try:
                        if path.stat().st_size > FS_MAX_READ_BYTES:
                            continue
                        if needle not in _read_text_file(path).lower():
                            continue
                    except Exception:
                        continue
                results.append(_entry(path))
                if len(results) >= max_results:
                    break
            if len(results) >= max_results or timed_out:
                break
        if len(results) >= max_results or timed_out:
            break

    return {
        "results": results,
        "scanned": scanned,
        "truncated": len(results) >= max_results,
        "timed_out": timed_out,
    }


def status(user: dict) -> dict:
    return {
        "enabled": FS_ENABLED,
        "server_mode": FS_SERVER_MODE,
        "can_assign_to_others": bool(
            FS_SERVER_MODE and user["role"] in (auth.ROLE_DEVELOPER, auth.ROLE_ADMIN)
        ),
        "roots": len(list_roots(user)),
        "max_read_bytes": FS_MAX_READ_BYTES,
        "max_text_chars": FS_MAX_TEXT_CHARS,
        "text_suffixes": sorted(TEXT_SUFFIXES),
        "document_suffixes": sorted(DOC_SUFFIXES),
        "indexing": False,
    }
