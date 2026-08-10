import os
import sqlite3
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

import auth

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
CODE_DB = DATA_DIR / "code.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

EPHEMERAL_TTL_SECONDS = 120


def _now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CODE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scripts (
                script_id   TEXT PRIMARY KEY,
                owner_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                language    TEXT NOT NULL,
                source      TEXT NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scripts_owner ON scripts (owner_id)"
        )
        conn.commit()
    finally:
        conn.close()


def create_ephemeral_token(user_id: int) -> str:
    token = "obs_run_" + secrets.token_urlsafe(32)
    now = _now()
    expires = now + EPHEMERAL_TTL_SECONDS
    conn = auth._connect()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, expires),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def revoke_ephemeral_token(token: str) -> None:
    if not token or not token.startswith("obs_run_"):
        return
    conn = auth._connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def purge_expired_tokens() -> None:
    conn = auth._connect()
    try:
        conn.execute(
            "DELETE FROM sessions WHERE token LIKE 'obs_run_%' AND expires_at < ?",
            (_now(),),
        )
        conn.commit()
    finally:
        conn.close()


def save_script(owner_id: int, name: str, language: str, source: str,
                script_id: Optional[str] = None) -> dict:
    now = _now()
    conn = _connect()
    try:
        if script_id:
            row = conn.execute(
                "SELECT owner_id FROM scripts WHERE script_id = ?", (script_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Script non trovato.")
            if row["owner_id"] != owner_id:
                raise PermissionError("Script non accessibile.")
            conn.execute(
                "UPDATE scripts SET name = ?, language = ?, source = ?, updated_at = ? "
                "WHERE script_id = ?",
                (name, language, source, now, script_id),
            )
        else:
            script_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO scripts (script_id, owner_id, name, language, source, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (script_id, owner_id, name, language, source, now, now),
            )
        conn.commit()
        return get_script(owner_id, script_id)
    finally:
        conn.close()


def get_script(owner_id: int, script_id: str) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM scripts WHERE script_id = ?", (script_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Script non trovato.")
        if row["owner_id"] != owner_id:
            raise PermissionError("Script non accessibile.")
        return dict(row)
    finally:
        conn.close()


def list_scripts(owner_id: int) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT script_id, name, language, created_at, updated_at "
            "FROM scripts WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_script(owner_id: int, script_id: str) -> None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT owner_id FROM scripts WHERE script_id = ?", (script_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Script non trovato.")
        if row["owner_id"] != owner_id:
            raise PermissionError("Script non accessibile.")
        conn.execute("DELETE FROM scripts WHERE script_id = ?", (script_id,))
        conn.commit()
    finally:
        conn.close()


def delete_user_scripts(user_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM scripts WHERE owner_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def reassign_scripts(from_user_id: int, to_user_id: int) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE scripts SET owner_id = ? WHERE owner_id = ?",
            (to_user_id, from_user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
