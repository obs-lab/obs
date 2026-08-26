import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

_OBS_DATA_ENV = os.environ.get("OBS_DATA_DIR", "").strip()
if _OBS_DATA_ENV:
    DATA_DIR = Path(_OBS_DATA_ENV)
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
AGENTS_DB = DATA_DIR / "agents.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

RUN_KEEP = int(os.environ.get("OBS_AGENT_RUN_KEEP", "500"))

STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"


def _now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(AGENTS_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id    TEXT PRIMARY KEY,
                owner_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                kind        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                config      TEXT NOT NULL,
                trigger     TEXT NOT NULL DEFAULT 'manual',
                interval_s  INTEGER NOT NULL DEFAULT 0,
                enabled     INTEGER NOT NULL DEFAULT 1,
                last_run_at REAL NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents (owner_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id      TEXT PRIMARY KEY,
                agent_id    TEXT NOT NULL,
                owner_id    INTEGER NOT NULL,
                trigger     TEXT NOT NULL,
                status      TEXT NOT NULL,
                steps       INTEGER NOT NULL DEFAULT 0,
                input       TEXT NOT NULL DEFAULT '',
                output      TEXT NOT NULL DEFAULT '',
                error       TEXT NOT NULL DEFAULT '',
                trace       TEXT NOT NULL DEFAULT '[]',
                started_at  REAL NOT NULL,
                ended_at    REAL NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_agent ON agent_runs (agent_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_owner ON agent_runs (owner_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_agent(row: sqlite3.Row) -> dict:
    out = dict(row)
    try:
        out["config"] = json.loads(out.get("config") or "{}")
    except Exception:
        out["config"] = {}
    out["enabled"] = bool(out.get("enabled"))
    return out


def save_agent(owner_id: int, name: str, kind: str, config: dict,
               description: str = "", trigger: str = "manual",
               interval_s: int = 0, enabled: bool = True,
               agent_id: Optional[str] = None) -> dict:
    now = _now()
    payload = json.dumps(config or {}, ensure_ascii=False)
    conn = _connect()
    try:
        if agent_id:
            row = conn.execute(
                "SELECT owner_id FROM agents WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Agente non trovato.")
            if row["owner_id"] != owner_id:
                raise PermissionError("Agente non accessibile.")
            conn.execute(
                "UPDATE agents SET name = ?, kind = ?, description = ?, config = ?, "
                "trigger = ?, interval_s = ?, enabled = ?, updated_at = ? "
                "WHERE agent_id = ?",
                (name, kind, description, payload, trigger, int(interval_s),
                 1 if enabled else 0, now, agent_id),
            )
        else:
            agent_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO agents (agent_id, owner_id, name, kind, description, config, "
                "trigger, interval_s, enabled, last_run_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_id, owner_id, name, kind, description, payload, trigger,
                 int(interval_s), 1 if enabled else 0, 0.0, now, now),
            )
        conn.commit()
    finally:
        conn.close()
    return get_agent(owner_id, agent_id)


def get_agent(owner_id: int, agent_id: str) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Agente non trovato.")
        if row["owner_id"] != owner_id:
            raise PermissionError("Agente non accessibile.")
        return _row_to_agent(row)
    finally:
        conn.close()


def list_agents(owner_id: int) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM agents WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner_id,),
        ).fetchall()
        return [_row_to_agent(r) for r in rows]
    finally:
        conn.close()


def due_agents(now: Optional[float] = None) -> list:
    stamp = _now() if now is None else now
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM agents WHERE enabled = 1 AND trigger = 'interval' "
            "AND interval_s > 0 AND (last_run_at + interval_s) <= ?",
            (stamp,),
        ).fetchall()
        return [_row_to_agent(r) for r in rows]
    finally:
        conn.close()


def mark_run_time(agent_id: str, stamp: Optional[float] = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE agents SET last_run_at = ? WHERE agent_id = ?",
            (_now() if stamp is None else stamp, agent_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_enabled(owner_id: int, agent_id: str, enabled: bool) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT owner_id FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Agente non trovato.")
        if row["owner_id"] != owner_id:
            raise PermissionError("Agente non accessibile.")
        conn.execute(
            "UPDATE agents SET enabled = ?, updated_at = ? WHERE agent_id = ?",
            (1 if enabled else 0, _now(), agent_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_agent(owner_id, agent_id)


def delete_agent(owner_id: int, agent_id: str) -> None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT owner_id FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Agente non trovato.")
        if row["owner_id"] != owner_id:
            raise PermissionError("Agente non accessibile.")
        conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        conn.execute("DELETE FROM agent_runs WHERE agent_id = ?", (agent_id,))
        conn.commit()
    finally:
        conn.close()


def delete_user_agents(user_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM agents WHERE owner_id = ?", (user_id,))
        conn.execute("DELETE FROM agent_runs WHERE owner_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def reassign_agents(from_user_id: int, to_user_id: int) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE agents SET owner_id = ? WHERE owner_id = ?",
            (to_user_id, from_user_id),
        )
        conn.execute(
            "UPDATE agent_runs SET owner_id = ? WHERE owner_id = ?",
            (to_user_id, from_user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def start_run(agent_id: str, owner_id: int, trigger: str, payload: str) -> str:
    run_id = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO agent_runs (run_id, agent_id, owner_id, trigger, status, "
            "steps, input, output, error, trace, started_at, ended_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, agent_id, owner_id, trigger, STATUS_RUNNING, 0,
             payload[:4000], "", "", "[]", _now(), 0.0),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def finish_run(run_id: str, status: str, output: str = "", error: str = "",
               steps: int = 0, trace: Optional[list] = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE agent_runs SET status = ?, output = ?, error = ?, steps = ?, "
            "trace = ?, ended_at = ? WHERE run_id = ?",
            (status, output[:20000], error[:4000], int(steps),
             json.dumps(trace or [], ensure_ascii=False)[:40000], _now(), run_id),
        )
        conn.commit()
    finally:
        conn.close()
    purge_old_runs()


def get_run(owner_id: int, run_id: str) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Esecuzione non trovata.")
        if row["owner_id"] != owner_id:
            raise PermissionError("Esecuzione non accessibile.")
        out = dict(row)
        try:
            out["trace"] = json.loads(out.get("trace") or "[]")
        except Exception:
            out["trace"] = []
        return out
    finally:
        conn.close()


def list_runs(owner_id: int, agent_id: Optional[str] = None, limit: int = 50) -> list:
    conn = _connect()
    try:
        if agent_id:
            rows = conn.execute(
                "SELECT run_id, agent_id, trigger, status, steps, started_at, ended_at "
                "FROM agent_runs WHERE owner_id = ? AND agent_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (owner_id, agent_id, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT run_id, agent_id, trigger, status, steps, started_at, ended_at "
                "FROM agent_runs WHERE owner_id = ? ORDER BY started_at DESC LIMIT ?",
                (owner_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def purge_old_runs(keep: int = RUN_KEEP) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM agent_runs WHERE run_id NOT IN "
            "(SELECT run_id FROM agent_runs ORDER BY started_at DESC LIMIT ?)",
            (int(keep),),
        )
        conn.commit()
    finally:
        conn.close()
