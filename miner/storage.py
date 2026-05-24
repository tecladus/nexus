"""
Persistencia local del minero usando SQLite.

Guarda:
- Tareas ejecutadas (con sus commits y reveals)
- Stats agregados (total ganado, slashed, etc.)
- Cache de modelos disponibles
- Reputación local

SQLite es perfecto acá: viene con Python, archivo único, sin servidor.
Para producción a gran escala (>10M tareas) migraríamos a PostgreSQL,
pero estamos lejos de eso.
"""

from __future__ import annotations
import sqlite3
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path
from enum import Enum


DEFAULT_DB_PATH = Path("nexus_miner.db")


def _json_default(obj):
    """Encoder JSON que sabe manejar Enums (DeterminismMode, etc.)."""
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _safe_dumps(obj) -> str:
    """json.dumps que maneja Enums."""
    return json.dumps(obj, default=_json_default)


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    client_id TEXT,
    kind TEXT,
    spec_json TEXT,
    payment_nxs REAL,
    status TEXT,
    received_at REAL,
    commit_hash TEXT,
    commit_at REAL,
    result TEXT,
    nonce TEXT,
    revealed_at REAL,
    verified_at REAL,
    paid_at REAL,
    compute_time_ms INTEGER,
    inference_metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_received ON tasks(received_at);

CREATE TABLE IF NOT EXISTS miner_stats (
    miner_id TEXT PRIMARY KEY,
    total_tasks_executed INTEGER DEFAULT 0,
    total_tasks_paid INTEGER DEFAULT 0,
    total_tasks_slashed INTEGER DEFAULT 0,
    total_earned_nxs REAL DEFAULT 0.0,
    total_slashed_nxs REAL DEFAULT 0.0,
    current_stake_nxs REAL DEFAULT 0.0,
    reputation_score REAL DEFAULT 1.0,
    last_updated REAL
);

CREATE TABLE IF NOT EXISTS events_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL,
    event_type TEXT,
    task_id TEXT,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events_log(timestamp);
"""


class MinerDB:
    """Acceso a la base de datos del minero."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        """Conexión con auto-commit en context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA_V1)
            # Marcar versión de schema
            conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")

    # ============================================================
    # Tasks
    # ============================================================

    def record_task_received(self, task_id: str, client_id: str, kind: str,
                              spec: dict, payment_nxs: float) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id, client_id, kind, spec_json, payment_nxs,
                    status, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (task_id, client_id, kind, _safe_dumps(spec), payment_nxs,
                 "received", time.time())
            )

    def record_commit(self, task_id: str, commit_hash: str,
                       compute_time_ms: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status = ?, commit_hash = ?, commit_at = ?,
                       compute_time_ms = ?
                   WHERE task_id = ?""",
                ("committed", commit_hash, time.time(), compute_time_ms, task_id)
            )

    def record_reveal(self, task_id: str, result: str, nonce: str,
                       metadata: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status = ?, result = ?, nonce = ?, revealed_at = ?,
                       inference_metadata = ?
                   WHERE task_id = ?""",
                ("revealed", result, nonce, time.time(),
                 _safe_dumps(metadata), task_id)
            )

    def record_payment(self, task_id: str, miner_id: str,
                        payment_nxs: float) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status = ?, paid_at = ?
                   WHERE task_id = ?""",
                ("paid", time.time(), task_id)
            )
            # Actualizar stats
            self._upsert_stats(conn, miner_id, paid_delta=1, earned_delta=payment_nxs)

    def record_slashing(self, task_id: str, miner_id: str,
                         slashed_nxs: float, reason: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status = ?
                   WHERE task_id = ?""",
                ("slashed", task_id)
            )
            self._upsert_stats(conn, miner_id, slashed_delta=1,
                                slashed_amount=slashed_nxs)
            conn.execute(
                """INSERT INTO events_log
                   (timestamp, event_type, task_id, details)
                   VALUES (?, ?, ?, ?)""",
                (time.time(), "SLASH", task_id,
                 _safe_dumps({"amount": slashed_nxs, "reason": reason}))
            )

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_recent_tasks(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT task_id, kind, status, payment_nxs, received_at,
                          compute_time_ms
                   FROM tasks
                   ORDER BY received_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ============================================================
    # Stats
    # ============================================================

    def _upsert_stats(self, conn, miner_id: str, executed_delta: int = 0,
                       paid_delta: int = 0, slashed_delta: int = 0,
                       earned_delta: float = 0.0,
                       slashed_amount: float = 0.0) -> None:
        # INSERT si no existe
        conn.execute(
            """INSERT OR IGNORE INTO miner_stats (miner_id, last_updated)
               VALUES (?, ?)""",
            (miner_id, time.time())
        )
        # UPDATE acumulando
        conn.execute(
            """UPDATE miner_stats
               SET total_tasks_executed = total_tasks_executed + ?,
                   total_tasks_paid = total_tasks_paid + ?,
                   total_tasks_slashed = total_tasks_slashed + ?,
                   total_earned_nxs = total_earned_nxs + ?,
                   total_slashed_nxs = total_slashed_nxs + ?,
                   last_updated = ?
               WHERE miner_id = ?""",
            (executed_delta, paid_delta, slashed_delta,
             earned_delta, slashed_amount, time.time(), miner_id)
        )

    def increment_executed(self, miner_id: str) -> None:
        with self._conn() as conn:
            self._upsert_stats(conn, miner_id, executed_delta=1)

    def get_stats(self, miner_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM miner_stats WHERE miner_id = ?", (miner_id,)
            ).fetchone()
            return dict(row) if row else None


# ============================================================
# Demo
# ============================================================

if __name__ == "__main__":
    import tempfile

    # Usar DB temporal para demo
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = Path(f.name)

    print("=" * 60)
    print(f"Demo de persistencia (DB temporal: {tmp_db})")
    print("=" * 60)

    db = MinerDB(tmp_db)
    miner_id = "test_miner"

    # Simular flujo de una tarea
    db.record_task_received(
        task_id="t001",
        client_id="alice",
        kind="llm_inference",
        spec={"model": "qwen2.5:7b", "prompt": "hola"},
        payment_nxs=5.0,
    )
    print("\n✓ Tarea recibida")

    db.record_commit("t001", "abc123def...", compute_time_ms=1500)
    print("✓ Commit registrado")

    db.record_reveal("t001", "Hola, ¿cómo estás?", "nonce_xyz",
                      metadata={"tokens": 6})
    print("✓ Reveal registrado")

    db.record_payment("t001", miner_id, 5.0)
    print("✓ Pago registrado")

    # Ver estado
    task = db.get_task("t001")
    print(f"\n📋 Tarea final: {task['status']}, pagado a las {task['paid_at']}")

    stats = db.get_stats(miner_id)
    print(f"\n📊 Stats:")
    print(f"   Total ejecutadas: {stats['total_tasks_executed']}")
    print(f"   Pagadas: {stats['total_tasks_paid']}")
    print(f"   Ganadas: {stats['total_earned_nxs']} NXS")

    # Cleanup
    tmp_db.unlink()
    print("\n✓ Cleanup OK")
