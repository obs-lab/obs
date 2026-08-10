import os
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import auth

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
SHARING_DB  = DATA_DIR / "sharing.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DOCUMENT = "document"
TARGET_FOLDER   = "folder"
VALID_TARGETS   = {TARGET_DOCUMENT, TARGET_FOLDER}

RECIPIENT_USER  = "user"
RECIPIENT_GROUP = "group"
VALID_RECIPIENTS = {RECIPIENT_USER, RECIPIENT_GROUP}


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SHARING_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS group_members (
                group_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                PRIMARY KEY (group_id, user_id),
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS shares (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id        INTEGER NOT NULL,
                target_type     TEXT NOT NULL,
                target_id       TEXT NOT NULL,
                recipient_type  TEXT NOT NULL,
                recipient_id    INTEGER NOT NULL,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS placements (
                user_id     INTEGER NOT NULL,
                doc_id      TEXT NOT NULL,
                folder_id   TEXT,
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (user_id, doc_id)
            );

            CREATE INDEX IF NOT EXISTS idx_groups_owner ON groups(owner_id);
            CREATE INDEX IF NOT EXISTS idx_members_user ON group_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_shares_owner ON shares(owner_id);
            CREATE INDEX IF NOT EXISTS idx_shares_recipient ON shares(recipient_type, recipient_id);
            CREATE INDEX IF NOT EXISTS idx_placements_user ON placements(user_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_group(owner_id: int, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Il nome del gruppo non puo' essere vuoto.")
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM groups WHERE owner_id = ? AND lower(name) = lower(?)",
            (owner_id, name),
        ).fetchone()
        if existing:
            raise ValueError("Hai gia' un gruppo con questo nome.")
        now = _iso(_now())
        cur = conn.execute(
            "INSERT INTO groups (owner_id, name, created_at) VALUES (?, ?, ?)",
            (owner_id, name[:100], now),
        )
        conn.commit()
        return {"id": cur.lastrowid, "owner_id": owner_id, "name": name[:100], "created_at": now}
    finally:
        conn.close()


def _owned_group(conn, owner_id: int, group_id: int):
    row = conn.execute(
        "SELECT id, owner_id, name, created_at FROM groups WHERE id = ?",
        (group_id,),
    ).fetchone()
    if not row:
        raise ValueError("Gruppo non trovato.")
    if row["owner_id"] != owner_id:
        raise ValueError("Non sei il proprietario di questo gruppo.")
    return row


def rename_group(owner_id: int, group_id: int, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Il nome del gruppo non puo' essere vuoto.")
    conn = _connect()
    try:
        _owned_group(conn, owner_id, group_id)
        clash = conn.execute(
            "SELECT id FROM groups WHERE owner_id = ? AND lower(name) = lower(?) AND id != ?",
            (owner_id, name, group_id),
        ).fetchone()
        if clash:
            raise ValueError("Hai gia' un gruppo con questo nome.")
        conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name[:100], group_id))
        conn.commit()
        return {"id": group_id, "owner_id": owner_id, "name": name[:100]}
    finally:
        conn.close()


def delete_group(owner_id: int, group_id: int) -> None:
    conn = _connect()
    try:
        _owned_group(conn, owner_id, group_id)
        conn.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
        conn.execute(
            "DELETE FROM shares WHERE recipient_type = ? AND recipient_id = ?",
            (RECIPIENT_GROUP, group_id),
        )
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()
    finally:
        conn.close()


def add_member(owner_id: int, group_id: int, user_id: int) -> None:
    conn = _connect()
    try:
        _owned_group(conn, owner_id, group_id)
        conn.execute(
            "INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)",
            (group_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def remove_member(owner_id: int, group_id: int, user_id: int) -> None:
    conn = _connect()
    try:
        _owned_group(conn, owner_id, group_id)
        conn.execute(
            "DELETE FROM group_members WHERE group_id = ? AND user_id = ?",
            (group_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def group_member_ids(group_id: int) -> set:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT user_id FROM group_members WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        return {r["user_id"] for r in rows}
    finally:
        conn.close()


def list_groups(owner_id: int) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, name, created_at FROM groups WHERE owner_id = ? ORDER BY lower(name)",
            (owner_id,),
        ).fetchall()
        out = []
        for r in rows:
            members = conn.execute(
                "SELECT user_id FROM group_members WHERE group_id = ?",
                (r["id"],),
            ).fetchall()
            out.append({
                "id":         r["id"],
                "name":       r["name"],
                "created_at": r["created_at"],
                "member_ids": [m["user_id"] for m in members],
            })
        return out
    finally:
        conn.close()


def create_share(owner_id: int, target_type: str, target_id: str,
                 recipient_type: str, recipient_id: int, is_owner=None) -> dict:
    if target_type not in VALID_TARGETS:
        raise ValueError("Tipo di elemento non valido.")
    if recipient_type not in VALID_RECIPIENTS:
        raise ValueError("Tipo di destinatario non valido.")
    target_id = (str(target_id) or "").strip()
    if not target_id:
        raise ValueError("Elemento da condividere mancante.")
    if recipient_type == RECIPIENT_USER and recipient_id == owner_id:
        raise ValueError("Non puoi condividere un elemento con te stesso.")
    if is_owner is not None and not is_owner(target_type, target_id, owner_id):
        raise PermissionError(
            "Solo il proprietario puo' condividere questo elemento. Un elemento "
            "ricevuto in condivisione non puo' essere ricondiviso.")
    conn = _connect()
    try:
        if recipient_type == RECIPIENT_GROUP:
            _owned_group(conn, owner_id, recipient_id)
        elif recipient_type == RECIPIENT_USER:
            if auth.get_user_by_id(recipient_id) is None:
                raise ValueError("Utente destinatario non trovato.")
        existing = conn.execute(
            "SELECT id FROM shares WHERE owner_id = ? AND target_type = ? AND target_id = ? "
            "AND recipient_type = ? AND recipient_id = ?",
            (owner_id, target_type, target_id, recipient_type, recipient_id),
        ).fetchone()
        if existing:
            return {"id": existing["id"], "already": True}
        now = _iso(_now())
        cur = conn.execute(
            "INSERT INTO shares (owner_id, target_type, target_id, recipient_type, "
            "recipient_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, target_type, target_id, recipient_type, recipient_id, now),
        )
        conn.commit()
        return {"id": cur.lastrowid, "already": False}
    finally:
        conn.close()


def purge_target(target_type: str, target_id: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM shares WHERE target_type = ? AND target_id = ?",
            (target_type, str(target_id)),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_share(owner_id: int, share_id: int) -> None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT owner_id FROM shares WHERE id = ?", (share_id,)
        ).fetchone()
        if not row:
            raise ValueError("Condivisione non trovata.")
        if row["owner_id"] != owner_id:
            raise ValueError("Non sei il proprietario di questa condivisione.")
        conn.execute("DELETE FROM shares WHERE id = ?", (share_id,))
        conn.commit()
    finally:
        conn.close()


def list_shares_by_owner(owner_id: int) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, target_type, target_id, recipient_type, recipient_id, created_at "
            "FROM shares WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _shares_for_user(user_id: int) -> list:
    conn = _connect()
    try:
        group_rows = conn.execute(
            "SELECT group_id FROM group_members WHERE user_id = ?", (user_id,)
        ).fetchall()
        group_ids = [r["group_id"] for r in group_rows]

        clauses = ["(recipient_type = ? AND recipient_id = ?)"]
        params = [RECIPIENT_USER, user_id]
        if group_ids:
            placeholders = ",".join("?" for _ in group_ids)
            clauses.append(f"(recipient_type = ? AND recipient_id IN ({placeholders}))")
            params.append(RECIPIENT_GROUP)
            params.extend(group_ids)

        sql = ("SELECT owner_id, target_type, target_id FROM shares WHERE "
               + " OR ".join(clauses))
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def shared_doc_ids(user_id: int, doc_owner_of=None, docs_in_folder=None) -> set:
    """Insieme dei doc_id condivisi con questo utente, direttamente o via gruppo.

    Le condivisioni di cartella sono risolte in modo dinamico tramite docs_in_folder,
    che per un folder_id restituisce i doc_id attualmente in quella cartella. Solo i
    documenti il cui owner coincide con l'owner della condivisione vengono inclusi,
    cosi' ognuno condivide unicamente cio' che possiede. doc_owner_of mappa doc_id
    sull'owner_id del documento."""
    result = set()
    shares = _shares_for_user(user_id)
    for s in shares:
        if s["target_type"] == TARGET_DOCUMENT:
            did = s["target_id"]
            if doc_owner_of is not None and doc_owner_of(did) == s["owner_id"]:
                result.add(did)
        elif s["target_type"] == TARGET_FOLDER:
            if docs_in_folder is None or doc_owner_of is None:
                continue
            for did in docs_in_folder(s["target_id"]):
                if doc_owner_of(did) == s["owner_id"]:
                    result.add(did)
    return result

def shared_doc_ids_split(user_id: int, doc_owner_of=None, docs_in_folder=None) -> dict:
    """Separa i doc_id ricevuti per condivisione diretta da quelli ricevuti
    attraverso la condivisione di una cartella. Un documento raggiunto per
    entrambe le vie conta come diretto, perche' la condivisione esplicita e'
    piu' forte del veicolo cartella."""
    direct = set()
    via_folder = set()
    for s in _shares_for_user(user_id):
        if s["target_type"] == TARGET_DOCUMENT:
            did = s["target_id"]
            if doc_owner_of is not None and doc_owner_of(did) == s["owner_id"]:
                direct.add(did)
        elif s["target_type"] == TARGET_FOLDER:
            if docs_in_folder is None or doc_owner_of is None:
                continue
            for did in docs_in_folder(s["target_id"]):
                if doc_owner_of(did) == s["owner_id"]:
                    via_folder.add(did)
    via_folder -= direct
    return {"direct": direct, "via_folder": via_folder}


def shared_folder_ids(user_id: int) -> set:
    """folder_id delle cartelle condivise con questo utente, direttamente o via gruppo."""
    return {s["target_id"] for s in _shares_for_user(user_id)
            if s["target_type"] == TARGET_FOLDER}


def get_placements(user_id: int) -> dict:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT doc_id, folder_id FROM placements WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {r["doc_id"]: r["folder_id"] for r in rows}
    finally:
        conn.close()


def set_placement(user_id: int, doc_id: str, folder_id: Optional[str]) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO placements (user_id, doc_id, folder_id, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, doc_id) DO UPDATE SET folder_id = excluded.folder_id, "
            "updated_at = excluded.updated_at",
            (user_id, doc_id, folder_id, _iso(_now())),
        )
        conn.commit()
    finally:
        conn.close()


def purge_placements_for_folder(folder_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE placements SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        conn.commit()
    finally:
        conn.close()


def purge_user(user_id: int) -> dict:
    """Rimuove ogni traccia di un utente cancellato: le condivisioni che ha
    concesso, quelle che ha ricevuto, i gruppi che possiede, le sue appartenenze
    ad altri gruppi e le sue collocazioni personali. Necessario perche' gli id
    utente sono AUTOINCREMENT: senza questa pulizia un futuro utente potrebbe
    ricevere lo stesso id ed ereditare accessi non suoi."""
    conn = _connect()
    try:
        owned_groups = [r["id"] for r in conn.execute(
            "SELECT id FROM groups WHERE owner_id = ?", (user_id,)).fetchall()]

        n_out = conn.execute(
            "DELETE FROM shares WHERE owner_id = ?", (user_id,)).rowcount
        n_in = conn.execute(
            "DELETE FROM shares WHERE recipient_type = ? AND recipient_id = ?",
            (RECIPIENT_USER, user_id)).rowcount

        n_grp_shares = 0
        for gid in owned_groups:
            n_grp_shares += conn.execute(
                "DELETE FROM shares WHERE recipient_type = ? AND recipient_id = ?",
                (RECIPIENT_GROUP, gid)).rowcount

        conn.execute("DELETE FROM group_members WHERE user_id = ?", (user_id,))
        n_groups = conn.execute(
            "DELETE FROM groups WHERE owner_id = ?", (user_id,)).rowcount
        n_place = conn.execute(
            "DELETE FROM placements WHERE user_id = ?", (user_id,)).rowcount
        conn.commit()
        return {
            "shares_granted": n_out,
            "shares_received": n_in + n_grp_shares,
            "groups": n_groups,
            "placements": n_place,
        }
    finally:
        conn.close()


def purge_placements_for_doc(doc_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM placements WHERE doc_id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
