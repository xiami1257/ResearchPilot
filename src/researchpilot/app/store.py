"""SQLite 持久化(stdlib sqlite3,零依赖零运维)。

表设计(两张,够用为止):
- sessions  一次研究任务的元数据 + 最终报告 markdown
- events    该任务的全部事件(JSON 落库)—— 回放历史、刷新恢复靠它

并发注意:SQLite 单写者。FastAPI 是异步多任务,任何"读改写"
都放进 with self._lock 串行化(见 save_event/upsert),防止
database is locked。读写都很快,任务量级不需要更复杂的东西。
"""
import json
import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    run_id      TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    status      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    error       TEXT,
    report_md   TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT NOT NULL,
    payload TEXT NOT NULL,          -- Event.to_dict() 的 JSON
    at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
"""


class Store:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        with self._lock, sqlite3.connect(db_path) as conn:
            conn.executescript(_SCHEMA)

    # -- 会话 -------------------------------------------------------------

    def create_session(self, run_id: str, topic: str, status: str, stage: str) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (run_id, topic, status, stage, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (run_id, topic, status, stage, _now()),
            )

    def update_session(
        self, run_id: str, *, status: str | None = None,
        stage: str | None = None, error: str | None = None,
        report_md: str | None = None,
    ) -> None:
        """部分更新:只覆盖传了值的列(None = 不改)。"""
        sets, params = [], []
        for col, val in (("status", status), ("stage", stage),
                         ("error", error), ("report_md", report_md)):
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        if not sets:
            return
        params.append(run_id)
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE run_id = ?", params)

    def get_session(self, run_id: str) -> dict | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sessions WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT run_id, topic, status, stage, created_at FROM sessions"
                " ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- 事件 -------------------------------------------------------------

    def save_event(self, run_id: str, payload: dict) -> None:
        """事件为纯追加;单独锁(与 update 共享同一把锁防写冲突)。"""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO events (run_id, payload, at) VALUES (?, ?, ?)",
                (run_id, json.dumps(payload, ensure_ascii=False), payload.get("at", _now())),
            )

    def list_events(self, run_id: str) -> list[dict]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
