import os
import sqlite3
import secrets
import hashlib
import hmac
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt

SESSION_IDLE_HOURS      = 8
MAX_FAILED_ATTEMPTS     = 5
LOCKOUT_MINUTES         = 15
SESSION_TOKEN_BYTES     = 32

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
AUTH_DB     = DATA_DIR / "auth.db"
ACCESS_LOG  = DATA_DIR / "access_log.jsonl"

DATA_DIR.mkdir(parents=True, exist_ok=True)

ROLE_DEVELOPER = "developer"
ROLE_ADMIN     = "admin"
ROLE_USER      = "user"
VALID_ROLES    = {ROLE_DEVELOPER, ROLE_ADMIN, ROLE_USER}


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(AUTH_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT UNIQUE NOT NULL,
                username        TEXT NOT NULL,
                azienda         TEXT NOT NULL DEFAULT '',
                password_hash   TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'user',
                active          INTEGER NOT NULL DEFAULT 1,
                must_change_pw  INTEGER NOT NULL DEFAULT 0,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until    REAL NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                last_login      TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                created_at  REAL NOT NULL,
                expires_at  REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "initials" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN initials TEXT NOT NULL DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def log_access(event: str, email: str, success: bool, detail: str = "") -> None:
    entry = {
        "timestamp": _iso(_now()),
        "event":     event,
        "email":     email,
        "success":   success,
        "detail":    detail,
    }
    try:
        with open(ACCESS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_access_log(limit: int = 100) -> list:
    if not ACCESS_LOG.exists():
        return []
    try:
        lines = ACCESS_LOG.read_text(encoding="utf-8").strip().split("\n")
        entries = [json.loads(l) for l in lines if l.strip()]
        return entries[-limit:][::-1]
    except Exception:
        return []


def create_user(email: str, username: str, password: str, role: str = ROLE_USER,
                azienda: str = "", must_change_pw: bool = False) -> dict:
    email = _normalize_email(email)
    if not email or "@" not in email:
        raise ValueError("Email non valida.")
    if not username or not username.strip():
        raise ValueError("Il nome utente non puo' essere vuoto.")
    if not password or len(password) < 6:
        raise ValueError("La password deve avere almeno 6 caratteri.")
    if role not in VALID_ROLES:
        raise ValueError("Ruolo non valido.")

    conn = _connect()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise ValueError("Esiste gia' un utente con questa email.")
        now = _iso(_now())
        ini = default_initials(username)
        cur = conn.execute(
            """INSERT INTO users
               (email, username, azienda, password_hash, role, active,
                must_change_pw, created_at, initials)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (email, username.strip(), azienda.strip(), _hash_password(password),
             role, 1 if must_change_pw else 0, now, ini),
        )
        conn.commit()
        uid = cur.lastrowid
        log_access("create_user", email, True, f"role={role}")
        return {"id": uid, "email": email, "username": username.strip(),
                "role": role, "azienda": azienda.strip()}
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[dict]:
    email = _normalize_email(email)
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users(requester_role: str, requester_azienda: str = "") -> list:
    conn = _connect()
    try:
        if requester_role == ROLE_DEVELOPER:
            rows = conn.execute(
                "SELECT id, email, username, azienda, role, active, initials, "
                "must_change_pw, locked_until, created_at, last_login "
                "FROM users ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, email, username, azienda, role, active, initials, "
                "must_change_pw, locked_until, created_at, last_login "
                "FROM users WHERE azienda = ? ORDER BY created_at DESC",
                (requester_azienda,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["locked"] = d.get("locked_until", 0) > _now()
            out.append(d)
        return out
    finally:
        conn.close()


def default_initials(username: str) -> str:
    parts = [p for p in (username or "").strip().split() if p]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def update_user(requester_id: int, requester_role: str, target_user_id: int,
                fields: dict) -> dict:
    target = get_user_by_id(target_user_id)
    if not target:
        raise ValueError("Utente non trovato.")

    is_self = requester_id == target_user_id
    is_developer = requester_role == ROLE_DEVELOPER

    if not is_self and not is_developer:
        raise PermissionError("Non hai i permessi per modificare questo utente.")

    if is_developer:
        allowed = {"email", "username", "azienda", "initials", "role", "active"}
    else:
        allowed = {"email", "username", "azienda", "initials"}

    updates = {}
    for key in allowed:
        if key in fields and fields[key] is not None:
            updates[key] = fields[key]

    if "email" in updates:
        email = _normalize_email(updates["email"])
        if not email or "@" not in email:
            raise ValueError("Email non valida.")
        conn = _connect()
        try:
            clash = conn.execute(
                "SELECT id FROM users WHERE email = ? AND id != ?",
                (email, target_user_id)).fetchone()
        finally:
            conn.close()
        if clash:
            raise ValueError("Esiste gia' un utente con questa email.")
        updates["email"] = email

    if "username" in updates:
        if not str(updates["username"]).strip():
            raise ValueError("Il nome utente non puo' essere vuoto.")
        updates["username"] = str(updates["username"]).strip()

    if "azienda" in updates:
        updates["azienda"] = str(updates["azienda"]).strip()

    if "initials" in updates:
        ini = str(updates["initials"]).strip().upper()[:3]
        if not ini:
            ini = default_initials(updates.get("username") or target["username"])
        updates["initials"] = ini

    if "role" in updates and updates["role"] not in VALID_ROLES:
        raise ValueError("Ruolo non valido.")

    if "active" in updates:
        updates["active"] = 1 if updates["active"] else 0

    if not updates:
        return get_user_by_id(target_user_id)

    would_remove_role = updates.get("role", target["role"]) != ROLE_DEVELOPER
    would_deactivate = "active" in updates and updates["active"] == 0
    if target["role"] == ROLE_DEVELOPER and target["active"] and (would_remove_role or would_deactivate):
        if count_active_developers() <= 1:
            raise ValueError(
                "Impossibile rimuovere o disattivare l'ultimo developer attivo. "
                "Creane un altro prima di modificare questo.")

    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [target_user_id]
    conn = _connect()
    try:
        conn.execute(f"UPDATE users SET {sets} WHERE id = ?", vals)
        conn.commit()
        log_access("update_user", target["email"], True,
                   f"by={requester_id} fields={list(updates.keys())}")
    finally:
        conn.close()
    return get_user_by_id(target_user_id)


def authenticate(email: str, password: str) -> dict:
    email = _normalize_email(email)

    user = get_user_by_email(email)
    if not user:
        log_access("login", email, False, "utente inesistente")
        raise ValueError("Email o password non corretti.")

    if not user["active"]:
        log_access("login", email, False, "account disattivato")
        raise ValueError("Account disattivato. Contatta l'amministratore.")

    if user["locked_until"] > _now():
        remaining = int((user["locked_until"] - _now()) / 60) + 1
        log_access("login", email, False, "account bloccato")
        raise ValueError(f"Account bloccato per troppi tentativi. Riprova tra {remaining} minuti.")

    if not _verify_password(password, user["password_hash"]):
        _register_failed_attempt(user)
        log_access("login", email, False, "password errata")
        raise ValueError("Email o password non corretti.")

    _reset_failed_attempts(user["id"])
    token = _create_session(user["id"])
    log_access("login", email, True, f"role={user['role']}")
    return {
        "token":          token,
        "user_id":        user["id"],
        "email":          user["email"],
        "username":       user["username"],
        "role":           user["role"],
        "azienda":        user["azienda"],
        "must_change_pw": bool(user["must_change_pw"]),
        "initials":       user["initials"] if user.get("initials") else default_initials(user["username"]),
    }


def _register_failed_attempt(user: dict) -> None:
    conn = _connect()
    try:
        attempts = user["failed_attempts"] + 1
        locked_until = user["locked_until"]
        detail = ""
        if attempts >= MAX_FAILED_ATTEMPTS:
            locked_until = _now() + LOCKOUT_MINUTES * 60
            attempts = 0
            detail = "lockout"
        conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, user["id"]),
        )
        conn.commit()
        if detail == "lockout":
            log_access("lockout", user["email"], False, f"{MAX_FAILED_ATTEMPTS} tentativi falliti")
    finally:
        conn.close()


def _reset_failed_attempts(user_id: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = 0, last_login = ? WHERE id = ?",
            (_iso(_now()), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def unlock_user(user_id: int) -> bool:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = ?",
            (user_id,),
        )
        conn.commit()
        u = get_user_by_id(user_id)
        if u:
            log_access("unlock", u["email"], True, "sblocco manuale")
        return True
    finally:
        conn.close()


def _create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    now = _now()
    expires = now + SESSION_IDLE_HOURS * 3600
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, expires),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def validate_session(token: str) -> Optional[dict]:
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        now = _now()
        if row["expires_at"] < now:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        new_expires = now + SESSION_IDLE_HOURS * 3600
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            (new_expires, token),
        )
        conn.commit()
        user = get_user_by_id(row["user_id"])
        if not user or not user["active"]:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return {
            "user_id":        user["id"],
            "email":          user["email"],
            "username":       user["username"],
            "role":           user["role"],
            "azienda":        user["azienda"],
            "must_change_pw": bool(user["must_change_pw"]),
            "initials":       user["initials"] if user.get("initials") else default_initials(user["username"]),
        }
    finally:
        conn.close()


def destroy_session(token: str) -> None:
    if not token:
        return
    conn = _connect()
    try:
        row = conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        if row:
            u = get_user_by_id(row["user_id"])
            if u:
                log_access("logout", u["email"], True, "")
    finally:
        conn.close()


def destroy_all_sessions(user_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def change_password(user_id: int, old_password: str, new_password: str) -> None:
    if not new_password or len(new_password) < 6:
        raise ValueError("La nuova password deve avere almeno 6 caratteri.")
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("Utente non trovato.")
    if not _verify_password(old_password, user["password_hash"]):
        raise ValueError("La password attuale non e' corretta.")
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_pw = 0 WHERE id = ?",
            (_hash_password(new_password), user_id),
        )
        conn.commit()
        log_access("change_password", user["email"], True, "")
    finally:
        conn.close()
    destroy_all_sessions(user_id)


def reset_password(target_user_id: int, new_temp_password: str) -> None:
    if not new_temp_password or len(new_temp_password) < 6:
        raise ValueError("La password temporanea deve avere almeno 6 caratteri.")
    user = get_user_by_id(target_user_id)
    if not user:
        raise ValueError("Utente non trovato.")
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_pw = 1, "
            "failed_attempts = 0, locked_until = 0 WHERE id = ?",
            (_hash_password(new_temp_password), target_user_id),
        )
        conn.commit()
        log_access("reset_password", user["email"], True, "password temporanea impostata")
    finally:
        conn.close()
    destroy_all_sessions(target_user_id)


def set_user_active(target_user_id: int, active: bool) -> None:
    if not active:
        u = get_user_by_id(target_user_id)
        if u and u["role"] == ROLE_DEVELOPER and u["active"] and count_active_developers() <= 1:
            raise ValueError(
                "Impossibile disattivare l'ultimo developer attivo. "
                "Creane un altro prima di disattivare questo.")
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET active = ? WHERE id = ?",
            (1 if active else 0, target_user_id),
        )
        conn.commit()
        u = get_user_by_id(target_user_id)
        if u:
            log_access("set_active", u["email"], True, f"active={active}")
    finally:
        conn.close()
    if not active:
        destroy_all_sessions(target_user_id)


def set_user_role(target_user_id: int, role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError("Ruolo non valido.")
    if role != ROLE_DEVELOPER:
        u = get_user_by_id(target_user_id)
        if u and u["role"] == ROLE_DEVELOPER and u["active"] and count_active_developers() <= 1:
            raise ValueError(
                "Impossibile cambiare il ruolo dell'ultimo developer attivo. "
                "Creane un altro prima di modificare questo.")
    conn = _connect()
    try:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, target_user_id))
        conn.commit()
        u = get_user_by_id(target_user_id)
        if u:
            log_access("set_role", u["email"], True, f"role={role}")
    finally:
        conn.close()


def delete_user(target_user_id: int) -> None:
    user = get_user_by_id(target_user_id)
    if not user:
        raise ValueError("Utente non trovato.")
    if user["role"] == ROLE_DEVELOPER and user["active"] and count_active_developers() <= 1:
        raise ValueError(
            "Impossibile eliminare l'ultimo developer attivo. "
            "Creane un altro prima di rimuovere questo.")
    conn = _connect()
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (target_user_id,))
        conn.commit()
        log_access("delete_user", user["email"], True, "")
    finally:
        conn.close()


def count_users() -> int:
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return row["n"]
    finally:
        conn.close()


def count_active_developers() -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = ? AND active = 1",
            (ROLE_DEVELOPER,),
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


def bootstrap_developer() -> Optional[str]:
    init_db()
    if count_users() > 0:
        return None
    email = _normalize_email(os.environ.get("DEV_EMAIL", ""))
    password = os.environ.get("DEV_PASSWORD", "")
    username = os.environ.get("DEV_USERNAME", "Developer")
    if not email or not password:
        return None
    create_user(email, username, password, role=ROLE_DEVELOPER,
                azienda=os.environ.get("DEV_AZIENDA", ""), must_change_pw=False)
    log_access("bootstrap", email, True, "account developer creato")
    return email


def developer_user_id() -> Optional[int]:
    """L'id del primo account developer, usato per attribuire gli oggetti legacy."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE role = ? ORDER BY id LIMIT 1",
            (ROLE_DEVELOPER,),
        ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def list_developers() -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, email, username, active FROM users WHERE role = ? ORDER BY id",
            (ROLE_DEVELOPER,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def recover_developer_password(email: str, new_password: str, provided_key: str) -> dict:
    expected_key = os.environ.get("OBS_RECOVERY_KEY", "")
    if not expected_key:
        raise PermissionError(
            "Recupero disabilitato: OBS_RECOVERY_KEY non e' configurata nell'ambiente.")
    if not provided_key or provided_key != expected_key:
        raise PermissionError("Chiave di recupero non valida.")

    user = get_user_by_email(email)
    if not user or user["role"] != ROLE_DEVELOPER:
        raise ValueError("Nessun developer corrisponde a questa email.")

    if not user["active"]:
        set_user_active(user["id"], True)

    reset_password(user["id"], new_password)
    log_access("recover_developer", user["email"], True, "password recuperata via chiave")
    return {"id": user["id"], "email": user["email"]}

