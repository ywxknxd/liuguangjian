from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Task:
    title: str
    due_date: str
    due_time: str = ""
    completed: bool = False
    remind: bool = False
    created_at: str = ""
    id: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.due_time:
            self.due_time = ""

    @classmethod
    def from_row(cls, row) -> "Task":
        return cls(
            id=row["id"],
            title=row["title"],
            due_date=row["due_date"],
            due_time=row["due_time"] or "",
            completed=bool(row["completed"]),
            remind=bool(row["remind"]),
            created_at=row["created_at"],
        )
