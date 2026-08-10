import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
CODE_FILES_DIR = DATA_DIR / "code_files"

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 200

ALLOWED_SUFFIXES = {
    ".csv", ".tsv", ".txt", ".json", ".xml", ".yaml", ".yml",
    ".dat", ".data", ".mat", ".npy", ".npz", ".parquet",
    ".xlsx", ".xls", ".ods",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".bmp",
    ".py", ".js", ".java", ".c", ".cpp", ".h", ".hpp", ".m", ".r",
    ".html", ".css", ".md", ".sql",
    ".zip", ".gz", ".tar",
}

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _now() -> float:
    return time.time()


def init_dirs() -> None:
    CODE_FILES_DIR.mkdir(parents=True, exist_ok=True)


def user_dir(user_id: int) -> Path:
    d = CODE_FILES_DIR / str(int(user_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_name(name: str) -> str:
    name = name.strip()

    if "/" in name or "\\" in name:
        raise ValueError("Il nome non puo' contenere percorsi.")
    if ".." in name:
        raise ValueError("Il nome non puo' contenere due punti consecutivi.")
    if not name or name in {".", ".."}:
        raise ValueError("Nome file non valido.")
    if not SAFE_NAME.match(name):
        raise ValueError(
            "Il nome puo' contenere solo lettere, numeri, punto, trattino "
            "e trattino basso."
        )
    if len(name) > 120:
        raise ValueError("Nome file troppo lungo.")

    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Estensione non consentita: {suffix or 'nessuna'}")

    return name


def _resolve(user_id: int, name: str) -> Path:
    base = user_dir(user_id).resolve()
    target = (base / _validate_name(name)).resolve()

    if base not in target.parents and target != base:
        raise PermissionError("Percorso fuori dall'area consentita.")

    return target


def total_size(user_id: int) -> int:
    base = user_dir(user_id)
    return sum(f.stat().st_size for f in base.iterdir() if f.is_file())


def list_files(user_id: int) -> list:
    base = user_dir(user_id)
    out = []

    for f in sorted(base.iterdir()):
        if not f.is_file():
            continue
        st = f.stat()
        out.append({
            "name": f.name,
            "size": st.st_size,
            "modified": st.st_mtime,
        })

    return out


def save_file(user_id: int, name: str, content: bytes) -> dict:
    name = _validate_name(name)

    if len(content) > MAX_FILE_BYTES:
        raise ValueError(
            f"File troppo grande: massimo {MAX_FILE_BYTES // (1024*1024)} MB."
        )

    base = user_dir(user_id)
    esistenti = list_files(user_id)
    nomi = {f["name"] for f in esistenti}

    if name not in nomi and len(esistenti) >= MAX_FILES:
        raise ValueError(f"Troppi file: massimo {MAX_FILES}.")

    occupato = total_size(user_id)
    vecchio = 0
    target = base / name
    if target.exists():
        vecchio = target.stat().st_size

    if occupato - vecchio + len(content) > MAX_TOTAL_BYTES:
        raise ValueError(
            f"Spazio esaurito: massimo {MAX_TOTAL_BYTES // (1024*1024)} MB in totale."
        )

    target.write_bytes(content)

    st = target.stat()
    return {"name": name, "size": st.st_size, "modified": st.st_mtime}


TEXT_SUFFIXES = {
    ".csv", ".tsv", ".txt", ".json", ".xml", ".yaml", ".yml",
    ".dat", ".data", ".md", ".sql", ".svg",
    ".py", ".js", ".java", ".c", ".cpp", ".h", ".hpp", ".m", ".r",
    ".html", ".css",
}

MAX_PREVIEW_BYTES = 2 * 1024 * 1024


def is_text(name: str) -> bool:
    return Path(name).suffix.lower() in TEXT_SUFFIXES


def read_text(user_id: int, name: str) -> dict:
    target = _resolve(user_id, name)

    if not target.is_file():
        raise ValueError("File non trovato.")

    suffix = target.suffix.lower()
    size = target.stat().st_size

    if suffix not in TEXT_SUFFIXES:
        return {
            "name": name,
            "readable": False,
            "reason": "binary",
            "size": size,
            "content": "",
            "truncated": False,
        }

    if size > MAX_PREVIEW_BYTES:
        raw = target.read_bytes()[:MAX_PREVIEW_BYTES]
        troncato = True
    else:
        raw = target.read_bytes()
        troncato = False

    if b"\x00" in raw[:4096]:
        return {
            "name": name,
            "readable": False,
            "reason": "binary",
            "size": size,
            "content": "",
            "truncated": False,
        }

    try:
        testo = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            testo = raw.decode("latin-1")
        except Exception:
            return {
                "name": name,
                "readable": False,
                "reason": "encoding",
                "size": size,
                "content": "",
                "truncated": False,
            }

    return {
        "name": name,
        "readable": True,
        "reason": "",
        "size": size,
        "content": testo,
        "truncated": troncato,
    }


def write_text(user_id: int, name: str, content: str) -> dict:
    if not is_text(name):
        raise ValueError("Questo tipo di file non e' modificabile.")
    return save_file(user_id, name, content.encode("utf-8"))


def read_file(user_id: int, name: str) -> bytes:
    target = _resolve(user_id, name)
    if not target.is_file():
        raise ValueError("File non trovato.")
    return target.read_bytes()


def delete_file(user_id: int, name: str) -> None:
    target = _resolve(user_id, name)
    if not target.is_file():
        raise ValueError("File non trovato.")
    target.unlink()


def clear_files(user_id: int) -> int:
    base = user_dir(user_id)
    n = 0
    for f in list(base.iterdir()):
        if f.is_file():
            f.unlink()
            n += 1
    return n


def copy_into(user_id: int, workdir: Path, skip: Optional[set] = None) -> int:
    base = user_dir(user_id)
    skip = skip or set()
    n = 0

    for f in base.iterdir():
        if not f.is_file() or f.name in skip:
            continue
        shutil.copy2(str(f), str(workdir / f.name))
        n += 1

    return n


def usage(user_id: int) -> dict:
    return {
        "files": len(list_files(user_id)),
        "used": total_size(user_id),
        "max_total": MAX_TOTAL_BYTES,
        "max_file": MAX_FILE_BYTES,
        "max_files": MAX_FILES,
    }
