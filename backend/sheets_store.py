import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
SHEETS_DB = DATA_DIR / "obs_sheets.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

MAX_CELLS = int(os.environ.get("OBS_SHEETS_MAX_CELLS", "100000"))
MAX_SHEETS = int(os.environ.get("OBS_SHEETS_MAX_SHEETS", "50"))

VALID_ROLES = {"x", "y", "z", "xerr", "yerr", "zerr", "label", "group", "none"}
VALID_KINDS = {"numeric", "text", "datetime"}

DEFAULT_ROWS = 100
DEFAULT_COLS = 4


class SheetsError(Exception):
    pass


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:16]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SHEETS_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workbooks (
                workbook_id TEXT PRIMARY KEY,
                owner_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS worksheets (
                sheet_id    TEXT PRIMARY KEY,
                workbook_id TEXT NOT NULL,
                name        TEXT NOT NULL,
                position    INTEGER NOT NULL,
                columns     TEXT NOT NULL,
                rows        TEXT NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                FOREIGN KEY (workbook_id) REFERENCES workbooks (workbook_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plots (
                plot_id     TEXT PRIMARY KEY,
                sheet_id    TEXT NOT NULL,
                name        TEXT NOT NULL,
                plot_type   TEXT NOT NULL,
                config      TEXT NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                FOREIGN KEY (sheet_id) REFERENCES worksheets (sheet_id)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wb_owner ON workbooks (owner_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_book ON worksheets (workbook_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plots_sheet ON plots (sheet_id)"
        )
        conn.commit()
    finally:
        conn.close()


def blank_columns(count: int = DEFAULT_COLS) -> List[Dict[str, Any]]:
    out = []
    for i in range(count):
        role = "x" if i == 0 else "y"
        out.append(
            {
                "name": chr(ord("A") + i) if i < 26 else "C" + str(i + 1),
                "role": role,
                "kind": "numeric",
                "units": "",
                "comment": "",
                "formula": "",
            }
        )
    return out


def blank_rows(nrows: int = DEFAULT_ROWS, ncols: int = DEFAULT_COLS) -> List[List[str]]:
    return [["" for _ in range(ncols)] for _ in range(nrows)]


def normalize_columns(columns: Any) -> List[Dict[str, Any]]:
    if not isinstance(columns, list) or not columns:
        raise SheetsError("Struttura delle colonne non valida.")
    out = []
    seen = set()
    for i, col in enumerate(columns):
        if not isinstance(col, dict):
            raise SheetsError("Descrittore di colonna non valido.")
        name = str(col.get("name") or "").strip()
        if not name:
            name = "C" + str(i + 1)
        base = name
        n = 2
        while name in seen:
            name = base + "_" + str(n)
            n += 1
        seen.add(name)
        role = str(col.get("role") or "none").lower()
        if role not in VALID_ROLES:
            role = "none"
        kind = str(col.get("kind") or "numeric").lower()
        if kind not in VALID_KINDS:
            kind = "numeric"
        out.append(
            {
                "name": name,
                "role": role,
                "kind": kind,
                "units": str(col.get("units") or "")[:64],
                "comment": str(col.get("comment") or "")[:256],
                "formula": str(col.get("formula") or "")[:512],
            }
        )
    return out


def normalize_rows(rows: Any, ncols: int) -> List[List[str]]:
    if not isinstance(rows, list):
        raise SheetsError("Struttura delle righe non valida.")
    total = len(rows) * max(ncols, 1)
    if total > MAX_CELLS:
        raise SheetsError(
            "Foglio troppo grande: "
            + str(total)
            + " celle, limite "
            + str(MAX_CELLS)
            + "."
        )
    out = []
    for row in rows:
        if not isinstance(row, list):
            row = []
        cells = ["" if c is None else str(c) for c in row[:ncols]]
        while len(cells) < ncols:
            cells.append("")
        out.append(cells)
    return out


def create_workbook(owner_id: int, name: str) -> Dict[str, Any]:
    wb_id = _uid("wb")
    sheet_id = _uid("ws")
    now = _now()
    clean_name = (name or "").strip() or "Cartella"
    cols = blank_columns()
    rows = blank_rows(DEFAULT_ROWS, len(cols))
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO workbooks (workbook_id, owner_id, name, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (wb_id, owner_id, clean_name, now, now),
        )
        conn.execute(
            "INSERT INTO worksheets (sheet_id, workbook_id, name, position, columns,"
            " rows, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sheet_id,
                wb_id,
                "Foglio1",
                0,
                json.dumps(cols),
                json.dumps(rows),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "workbook_id": wb_id,
        "name": clean_name,
        "created_at": now,
        "updated_at": now,
        "sheets": [{"sheet_id": sheet_id, "name": "Foglio1", "position": 0}],
    }


def list_workbooks(owner_id: int) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT workbook_id, name, created_at, updated_at FROM workbooks"
            " WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner_id,),
        ).fetchall()
        out = []
        for r in rows:
            sheets = conn.execute(
                "SELECT sheet_id, name, position FROM worksheets"
                " WHERE workbook_id = ? ORDER BY position",
                (r["workbook_id"],),
            ).fetchall()
            out.append(
                {
                    "workbook_id": r["workbook_id"],
                    "name": r["name"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "sheets": [dict(s) for s in sheets],
                }
            )
        return out
    finally:
        conn.close()


def get_workbook(owner_id: int, workbook_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT workbook_id, name, created_at, updated_at FROM workbooks"
            " WHERE workbook_id = ? AND owner_id = ?",
            (workbook_id, owner_id),
        ).fetchone()
        if not r:
            return None
        sheets = conn.execute(
            "SELECT sheet_id, name, position FROM worksheets"
            " WHERE workbook_id = ? ORDER BY position",
            (workbook_id,),
        ).fetchall()
        return {
            "workbook_id": r["workbook_id"],
            "name": r["name"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "sheets": [dict(s) for s in sheets],
        }
    finally:
        conn.close()


def rename_workbook(owner_id: int, workbook_id: str, name: str) -> bool:
    clean = (name or "").strip()
    if not clean:
        raise SheetsError("Nome non valido.")
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE workbooks SET name = ?, updated_at = ?"
            " WHERE workbook_id = ? AND owner_id = ?",
            (clean, _now(), workbook_id, owner_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_workbook(owner_id: int, workbook_id: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM workbooks WHERE workbook_id = ? AND owner_id = ?",
            (workbook_id, owner_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_sheet(owner_id: int, workbook_id: str, name: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        owner = conn.execute(
            "SELECT 1 FROM workbooks WHERE workbook_id = ? AND owner_id = ?",
            (workbook_id, owner_id),
        ).fetchone()
        if not owner:
            return None
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM worksheets WHERE workbook_id = ?",
            (workbook_id,),
        ).fetchone()["n"]
        if count >= MAX_SHEETS:
            raise SheetsError(
                "Numero massimo di fogli raggiunto: " + str(MAX_SHEETS) + "."
            )
        sheet_id = _uid("ws")
        now = _now()
        clean = (name or "").strip() or ("Foglio" + str(count + 1))
        cols = blank_columns()
        rows = blank_rows(DEFAULT_ROWS, len(cols))
        conn.execute(
            "INSERT INTO worksheets (sheet_id, workbook_id, name, position, columns,"
            " rows, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sheet_id,
                workbook_id,
                clean,
                count,
                json.dumps(cols),
                json.dumps(rows),
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE workbooks SET updated_at = ? WHERE workbook_id = ?",
            (now, workbook_id),
        )
        conn.commit()
        return {"sheet_id": sheet_id, "name": clean, "position": count}
    finally:
        conn.close()


def get_sheet(owner_id: int, sheet_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT w.sheet_id, w.workbook_id, w.name, w.position, w.columns, w.rows,"
            " w.created_at, w.updated_at FROM worksheets w"
            " JOIN workbooks b ON b.workbook_id = w.workbook_id"
            " WHERE w.sheet_id = ? AND b.owner_id = ?",
            (sheet_id, owner_id),
        ).fetchone()
        if not r:
            return None
        return {
            "sheet_id": r["sheet_id"],
            "workbook_id": r["workbook_id"],
            "name": r["name"],
            "position": r["position"],
            "columns": json.loads(r["columns"]),
            "rows": json.loads(r["rows"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
    finally:
        conn.close()


def save_sheet(
    owner_id: int,
    sheet_id: str,
    name: Optional[str],
    columns: Any,
    rows: Any,
) -> Optional[Dict[str, Any]]:
    cols = normalize_columns(columns)
    data = normalize_rows(rows, len(cols))
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT w.workbook_id, w.name FROM worksheets w"
            " JOIN workbooks b ON b.workbook_id = w.workbook_id"
            " WHERE w.sheet_id = ? AND b.owner_id = ?",
            (sheet_id, owner_id),
        ).fetchone()
        if not r:
            return None
        now = _now()
        clean = (name or "").strip() or r["name"]
        conn.execute(
            "UPDATE worksheets SET name = ?, columns = ?, rows = ?, updated_at = ?"
            " WHERE sheet_id = ?",
            (clean, json.dumps(cols), json.dumps(data), now, sheet_id),
        )
        conn.execute(
            "UPDATE workbooks SET updated_at = ? WHERE workbook_id = ?",
            (now, r["workbook_id"]),
        )
        conn.commit()
        return {
            "sheet_id": sheet_id,
            "name": clean,
            "columns": cols,
            "rows": data,
            "updated_at": now,
        }
    finally:
        conn.close()


def delete_sheet(owner_id: int, sheet_id: str) -> bool:
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT w.workbook_id FROM worksheets w"
            " JOIN workbooks b ON b.workbook_id = w.workbook_id"
            " WHERE w.sheet_id = ? AND b.owner_id = ?",
            (sheet_id, owner_id),
        ).fetchone()
        if not r:
            return False
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM worksheets WHERE workbook_id = ?",
            (r["workbook_id"],),
        ).fetchone()["n"]
        if remaining <= 1:
            raise SheetsError("Una cartella deve contenere almeno un foglio.")
        conn.execute("DELETE FROM worksheets WHERE sheet_id = ?", (sheet_id,))
        conn.execute(
            "UPDATE workbooks SET updated_at = ? WHERE workbook_id = ?",
            (_now(), r["workbook_id"]),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def save_plot(
    owner_id: int,
    sheet_id: str,
    name: str,
    plot_type: str,
    config: Dict[str, Any],
    plot_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT 1 FROM worksheets w JOIN workbooks b"
            " ON b.workbook_id = w.workbook_id"
            " WHERE w.sheet_id = ? AND b.owner_id = ?",
            (sheet_id, owner_id),
        ).fetchone()
        if not r:
            return None
        now = _now()
        clean = (name or "").strip() or plot_type
        if plot_id:
            cur = conn.execute(
                "UPDATE plots SET name = ?, plot_type = ?, config = ?, updated_at = ?"
                " WHERE plot_id = ? AND sheet_id = ?",
                (clean, plot_type, json.dumps(config), now, plot_id, sheet_id),
            )
            if cur.rowcount == 0:
                return None
        else:
            plot_id = _uid("pl")
            conn.execute(
                "INSERT INTO plots (plot_id, sheet_id, name, plot_type, config,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (plot_id, sheet_id, clean, plot_type, json.dumps(config), now, now),
            )
        conn.commit()
        return {
            "plot_id": plot_id,
            "sheet_id": sheet_id,
            "name": clean,
            "plot_type": plot_type,
            "config": config,
        }
    finally:
        conn.close()


def list_plots(owner_id: int, sheet_id: str) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT p.plot_id, p.name, p.plot_type, p.config, p.updated_at"
            " FROM plots p JOIN worksheets w ON w.sheet_id = p.sheet_id"
            " JOIN workbooks b ON b.workbook_id = w.workbook_id"
            " WHERE p.sheet_id = ? AND b.owner_id = ? ORDER BY p.updated_at DESC",
            (sheet_id, owner_id),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "plot_id": r["plot_id"],
                    "name": r["name"],
                    "plot_type": r["plot_type"],
                    "config": json.loads(r["config"]),
                    "updated_at": r["updated_at"],
                }
            )
        return out
    finally:
        conn.close()


def delete_plot(owner_id: int, plot_id: str) -> bool:
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT p.plot_id FROM plots p JOIN worksheets w ON w.sheet_id = p.sheet_id"
            " JOIN workbooks b ON b.workbook_id = w.workbook_id"
            " WHERE p.plot_id = ? AND b.owner_id = ?",
            (plot_id, owner_id),
        ).fetchone()
        if not r:
            return False
        conn.execute("DELETE FROM plots WHERE plot_id = ?", (plot_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def reassign_workbooks(user_id: int, new_owner_id: int) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE workbooks SET owner_id = ?, updated_at = ? WHERE owner_id = ?",
            (new_owner_id, _now(), user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
