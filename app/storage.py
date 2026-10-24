import os
import sqlite3
from typing import List, Optional

from app.models import Task


class TaskStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    due_time TEXT,
                    priority TEXT DEFAULT 'normal',
                    completed INTEGER NOT NULL DEFAULT 0,
                    remind INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            # 迁移旧表：如果 remind 列不存在则添加
            try:
                conn.execute("SELECT remind FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE tasks ADD COLUMN remind INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def add_task(self, task: Task) -> Task:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (title, due_date, due_time, completed, remind, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task.title,
                    task.due_date,
                    task.due_time,
                    1 if task.completed else 0,
                    1 if task.remind else 0,
                    task.created_at,
                ),
            )
            task.id = cursor.lastrowid
            conn.commit()
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, due_date, due_time, completed, remind, created_at FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return Task.from_row(row) if row else None

    def list_tasks(self, day: Optional[str] = None, search: str = "") -> List[Task]:
        query = "SELECT id, title, due_date, due_time, completed, remind, created_at FROM tasks"
        params = []
        clauses = []

        if day:
            clauses.append("due_date = ?")
            params.append(day)

        if search:
            clauses.append("title LIKE ?")
            params.append(f"%{search}%")

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " ORDER BY completed ASC, due_time ASC, created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [Task.from_row(row) for row in rows]

    def update_task(self, task: Task) -> Task:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET title = ?, due_date = ?, due_time = ?, completed = ?, remind = ?
                WHERE id = ?
                """,
                (
                    task.title,
                    task.due_date,
                    task.due_time,
                    1 if task.completed else 0,
                    1 if task.remind else 0,
                    task.id,
                ),
            )
            conn.commit()
        return task

    def delete_task(self, task_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()

    def complete_task(self, task_id: int) -> Optional[Task]:
        task = self.get_task(task_id)
        if task is None:
            return None
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
            conn.commit()
        task.completed = True
        return task

    def uncomplete_task(self, task_id: int) -> Optional[Task]:
        """将已完成任务恢复为未完成状态。"""
        task = self.get_task(task_id)
        if task is None:
            return None
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET completed = 0 WHERE id = ?", (task_id,))
            conn.commit()
        task.completed = False
        return task
