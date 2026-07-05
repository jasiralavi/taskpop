from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

APP_NAME = "taskpop"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def xdg_config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def xdg_data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


@dataclass
class TaskList:
    id: str
    title: str
    source: str = "local"
    google_list_id: str | None = None


@dataclass
class Task:
    id: str
    list_id: str
    title: str
    notes: str | None
    status: str
    google_task_id: str | None
    is_dirty: int
    sort_order: int
    updated_at: str
    completed_at: str | None = None


class Config:
    def __init__(self) -> None:
        self.dir = xdg_config_dir()
        self.path = self.dir / "config.json"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()


class TaskDB:
    def __init__(self, path: Path | None = None) -> None:
        self.data_dir = xdg_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = path or self.data_dir / "taskpop.db"
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()
        self.ensure_default_list()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS lists (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'local',
                google_list_id TEXT UNIQUE,
                last_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                list_id TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'needsAction',
                due_date TEXT,
                google_task_id TEXT UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                is_dirty INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY(list_id) REFERENCES lists(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_list_status ON tasks(list_id, status, is_deleted);
            CREATE INDEX IF NOT EXISTS idx_tasks_dirty ON tasks(is_dirty);
            """
        )
        self.conn.commit()

    def ensure_default_list(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM lists").fetchone()
        if row and row["c"] == 0:
            self.create_list("My Tasks", last_used=True)

    def create_list(self, title: str, source: str = "local", google_list_id: str | None = None, last_used: bool = False) -> str:
        list_id = str(uuid.uuid4())
        ts = now_iso()
        self.conn.execute(
            """
            INSERT INTO lists(id, title, source, google_list_id, last_used, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (list_id, title, source, google_list_id, 1 if last_used else 0, ts, ts),
        )
        if last_used:
            self.set_last_list(list_id)
        self.conn.commit()
        return list_id

    def upsert_google_list(self, title: str, google_list_id: str) -> str:
        ts = now_iso()
        row = self.conn.execute(
            "SELECT id FROM lists WHERE google_list_id = ?", (google_list_id,)
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE lists SET title = ?, source = 'google', updated_at = ? WHERE id = ?",
                (title, ts, row["id"]),
            )
            self.conn.commit()
            return row["id"]
        return self.create_list(title, source="google", google_list_id=google_list_id)

    def list_lists(self) -> list[TaskList]:
        # Use a stable order for keyboard cycling.
        #
        # Older versions sorted by last_used/updated_at. That made Ctrl+Tab
        # appear to switch only between the last two lists because every switch
        # changed last_used and updated_at, reordering the list before the next
        # Ctrl+Tab press.
        rows = self.conn.execute(
            """
            SELECT id, title, source, google_list_id
            FROM lists
            ORDER BY created_at ASC, title COLLATE NOCASE ASC
            """
        ).fetchall()
        return [TaskList(**dict(r)) for r in rows]

    def get_last_list(self) -> TaskList:
        row = self.conn.execute(
            "SELECT id, title, source, google_list_id FROM lists ORDER BY last_used DESC, updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            self.ensure_default_list()
            row = self.conn.execute(
                "SELECT id, title, source, google_list_id FROM lists LIMIT 1"
            ).fetchone()
        return TaskList(**dict(row))

    def set_last_list(self, list_id: str) -> None:
        self.conn.execute("UPDATE lists SET last_used = 0")
        self.conn.execute("UPDATE lists SET last_used = 1, updated_at = ? WHERE id = ?", (now_iso(), list_id))
        self.conn.commit()

    def add_task(self, list_id: str, title: str, notes: str | None = None, google_task_id: str | None = None, dirty: bool = True) -> str:
        title = title.strip()
        if not title:
            raise ValueError("Task title cannot be empty")
        task_id = str(uuid.uuid4())
        ts = now_iso()
        order_row = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM tasks WHERE list_id = ?",
            (list_id,),
        ).fetchone()
        sort_order = int(order_row["next_order"] or 1)
        self.conn.execute(
            """
            INSERT INTO tasks(id, list_id, title, notes, status, google_task_id, sort_order,
                              is_deleted, is_dirty, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, 'needsAction', ?, ?, 0, ?, ?, ?, NULL)
            """,
            (task_id, list_id, title, notes, google_task_id, sort_order, 1 if dirty else 0, ts, ts),
        )
        self.conn.commit()
        return task_id

    def upsert_google_task(
        self,
        list_id: str,
        title: str,
        google_task_id: str,
        status: str = "needsAction",
        notes: str | None = None,
        completed_at: str | None = None,
    ) -> str:
        ts = now_iso()
        row = self.conn.execute(
            "SELECT id FROM tasks WHERE google_task_id = ?", (google_task_id,)
        ).fetchone()
        if row:
            self.conn.execute(
                """
                UPDATE tasks
                SET title = ?, notes = ?, status = ?, completed_at = ?, is_deleted = 0,
                    is_dirty = 0, updated_at = ?
                WHERE id = ? AND is_dirty = 0
                """,
                (title, notes, status, completed_at, ts, row["id"]),
            )
            self.conn.commit()
            return row["id"]
        return self.add_task(list_id, title, notes=notes, google_task_id=google_task_id, dirty=False)

    def list_tasks(self, list_id: str, include_completed_ids: set[str] | None = None, filter_text: str = "") -> list[Task]:
        include_completed_ids = include_completed_ids or set()
        params: list = [list_id]
        clauses = ["list_id = ?", "is_deleted = 0"]

        if include_completed_ids:
            placeholders = ",".join("?" for _ in include_completed_ids)
            clauses.append(f"(status = 'needsAction' OR id IN ({placeholders}))")
            params.extend(list(include_completed_ids))
        else:
            clauses.append("status = 'needsAction'")

        if filter_text.strip():
            clauses.append("LOWER(title) LIKE ?")
            params.append(f"%{filter_text.strip().lower()}%")

        query = f"""
            SELECT id, list_id, title, notes, status, google_task_id, is_dirty, sort_order, updated_at, completed_at
            FROM tasks
            WHERE {' AND '.join(clauses)}
            ORDER BY status ASC, sort_order ASC, updated_at DESC
        """
        rows = self.conn.execute(query, params).fetchall()
        return [Task(**dict(r)) for r in rows]

    def toggle_task(self, task_id: str) -> str:
        row = self.conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        new_status = "completed" if row["status"] != "completed" else "needsAction"
        completed_at = now_iso() if new_status == "completed" else None
        self.conn.execute(
            """
            UPDATE tasks
            SET status = ?, completed_at = ?, is_dirty = 1, updated_at = ?
            WHERE id = ?
            """,
            (new_status, completed_at, now_iso(), task_id),
        )
        self.conn.commit()
        return new_status

    def update_google_task_id(self, task_id: str, google_task_id: str) -> None:
        self.conn.execute(
            "UPDATE tasks SET google_task_id = ?, is_dirty = 0, updated_at = ? WHERE id = ?",
            (google_task_id, now_iso(), task_id),
        )
        self.conn.commit()

    def mark_clean(self, task_id: str) -> None:
        self.conn.execute("UPDATE tasks SET is_dirty = 0 WHERE id = ?", (task_id,))
        self.conn.commit()

    def dirty_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            """
            SELECT id, list_id, title, notes, status, google_task_id, is_dirty, sort_order, updated_at, completed_at
            FROM tasks
            WHERE is_dirty = 1 AND is_deleted = 0
            ORDER BY updated_at ASC
            """
        ).fetchall()
        return [Task(**dict(r)) for r in rows]

    def delete_list(self, list_id: str) -> None:
        self.conn.execute("DELETE FROM tasks WHERE list_id = ?", (list_id,))
        self.conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
        self.conn.commit()
        self.ensure_default_list()

    def get_list(self, list_id: str) -> TaskList | None:
        row = self.conn.execute(
            "SELECT id, title, source, google_list_id FROM lists WHERE id = ?", (list_id,)
        ).fetchone()
        return TaskList(**dict(row)) if row else None

    def count_dirty(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE is_dirty = 1").fetchone()
        return int(row["c"] if row else 0)
