"""JSON-file storage for the to-do app."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

MAX_TASK_LENGTH = 200


class TodoStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.todos: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []  # a corrupt file should not crash the app
        return [
            todo for todo in data.get("todos", [])
            if isinstance(todo, dict) and {"id", "task", "completed"} <= todo.keys()
        ]

    def _save(self) -> None:
        self.path.write_text(json.dumps({"todos": self.todos}, indent=2), encoding="utf-8")

    def _find(self, todo_id: str) -> dict:
        for todo in self.todos:
            if todo["id"] == todo_id:
                return todo
        raise KeyError(f"no todo with id {todo_id}")

    def add(self, task: str) -> dict:
        task = task.strip()
        if not task:
            raise ValueError("Task cannot be empty.")
        if len(task) > MAX_TASK_LENGTH:
            raise ValueError(f"Task must be at most {MAX_TASK_LENGTH} characters.")
        todo = {"id": uuid.uuid4().hex, "task": task, "completed": False}
        self.todos.append(todo)
        self._save()
        return todo

    def set_completed(self, todo_id: str, completed: bool) -> None:
        self._find(todo_id)["completed"] = completed
        self._save()

    def delete(self, todo_id: str) -> None:
        self.todos.remove(self._find(todo_id))
        self._save()

    def clear_completed(self) -> int:
        before = len(self.todos)
        self.todos = [todo for todo in self.todos if not todo["completed"]]
        self._save()
        return before - len(self.todos)
