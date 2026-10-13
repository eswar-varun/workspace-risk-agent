"""The project tracker: one row per task, parsed and validated.

Real trackers are messy, so problems in individual rows (an unknown status, an unreadable
date, a duplicate ID) are recorded as data issues and reported, never silently dropped and
never allowed to crash the whole analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    NOT_STARTED = "Not started"
    IN_PROGRESS = "In progress"
    BLOCKED = "Blocked"
    DONE = "Done"


_STATUS_ALIASES = {
    **dict.fromkeys(("not started", "todo", "to do", "open", "new", "backlog"), Status.NOT_STARTED),
    **dict.fromkeys(("in progress", "in-progress", "doing", "wip", "started"), Status.IN_PROGRESS),
    **dict.fromkeys(("blocked", "on hold", "waiting"), Status.BLOCKED),
    **dict.fromkeys(("done", "complete", "completed", "closed", "shipped"), Status.DONE),
}

# Accepted header names for each field, compared case-insensitively.
_COLUMNS = {
    "id": ("id", "task id", "key", "ticket"),
    "title": ("task", "title", "summary", "name"),
    "workstream": ("workstream", "team", "area", "stream"),
    "owner": ("owner", "assignee", "assigned to"),
    "status": ("status", "state"),
    "due": ("due", "due date", "deadline", "target date"),
    "depends_on": ("depends on", "dependencies", "blocked by", "prerequisites"),
    "last_update": ("last update", "last updated", "updated"),
}
_REQUIRED = ("id", "title", "status")

# Google Sheets serial dates count days from 30 December 1899.
_SHEETS_EPOCH = date(1899, 12, 30)


class TrackerError(ValueError):
    """The sheet can't be read as a tracker at all (e.g. a required column is missing)."""


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    status: Status
    workstream: str = ""
    owner: str = ""
    due: date | None = None
    depends_on: tuple[str, ...] = ()
    last_update: date | None = None

    @property
    def is_open(self) -> bool:
        return self.status is not Status.DONE


@dataclass
class Tracker:
    tasks: dict[str, Task]  # in sheet order
    issues: list[str] = field(default_factory=list)


def parse_date(value: Any) -> date | None:
    """Accept a Sheets serial number or an ISO date (YYYY-MM-DD); anything else is an error.

    Formatted strings like 10/9/2026 are refused on purpose: whether that's 9 October or
    10 September depends on the spreadsheet's locale, and guessing wrong silently moves
    deadlines. The Sheets connector requests serial numbers, which are unambiguous.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a date: {value!r}")
    if isinstance(value, int | float):
        return _SHEETS_EPOCH + timedelta(days=int(value))
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return _SHEETS_EPOCH + timedelta(days=int(float(text)))
    raise ValueError(f"unrecognised date {text!r} (use YYYY-MM-DD)")


def parse_rows(rows: list[list[Any]]) -> Tracker:
    if not rows:
        raise TrackerError("the tracker sheet is empty")
    header = [str(cell).strip().lower() for cell in rows[0]]
    index: dict[str, int] = {}
    for name, aliases in _COLUMNS.items():
        for position, title in enumerate(header):
            if title in aliases:
                index[name] = position
                break
    missing = [name for name in _REQUIRED if name not in index]
    if missing:
        raise TrackerError(f"the tracker is missing required column(s): {', '.join(missing)} "
                           f"(found: {', '.join(h for h in header if h) or 'none'})")

    tracker = Tracker(tasks={})
    for line, row in enumerate(rows[1:], start=2):
        def cell(name: str, row: list[Any] = row) -> Any:
            position = index.get(name)
            return row[position] if position is not None and position < len(row) else ""

        task_id = str(cell("id")).strip()
        if not task_id:
            if any(str(value).strip() for value in row):
                tracker.issues.append(f"row {line}: no task ID, row skipped")
            continue
        if task_id in tracker.tasks:
            tracker.issues.append(f"row {line}: duplicate ID {task_id}, row skipped")
            continue

        raw_status = str(cell("status")).strip()
        status = _STATUS_ALIASES.get(raw_status.lower())
        if status is None:
            tracker.issues.append(
                f"{task_id}: unknown status {raw_status!r}, treated as Not started")
            status = Status.NOT_STARTED

        tracker.tasks[task_id] = Task(
            id=task_id,
            title=str(cell("title")).strip(),
            status=status,
            workstream=str(cell("workstream")).strip(),
            owner=str(cell("owner")).strip(),
            due=_date(cell("due"), task_id, "due date", tracker.issues),
            depends_on=tuple(dict.fromkeys(
                d for d in re.split(r"[,;\s]+", str(cell("depends_on")).strip()) if d)),
            last_update=_date(cell("last_update"), task_id, "last update", tracker.issues),
        )
    return tracker


def _date(value: Any, task_id: str, what: str, issues: list[str]) -> date | None:
    try:
        return parse_date(value)
    except ValueError as exc:
        issues.append(f"{task_id}: {what} ignored, {exc}")
        return None
