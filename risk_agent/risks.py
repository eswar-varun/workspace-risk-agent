"""Project risk analysis, done in code.

The model is good at explaining and prioritising; it is unreliable at date arithmetic and
graph traversal. So every risk here is computed deterministically and is unit-tested, and
the agent's job is to explain the report, not to produce it.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .tracker import Status, Task, Tracker

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}


@dataclass(frozen=True)
class TaskRisk:
    task_id: str
    title: str
    owner: str
    workstream: str
    status: str
    due: str | None
    severity: str  # critical | high | medium
    flags: tuple[str, ...]
    reasons: tuple[str, ...]
    days_overdue: int
    impact: int  # open tasks downstream that can't finish until this one does
    affects: tuple[str, ...]
    waiting_on: tuple[str, ...]  # blocked or overdue tasks upstream of this one


@dataclass(frozen=True)
class OwnerLoad:
    owner: str
    task_ids: tuple[str, ...]


@dataclass(frozen=True)
class RiskReport:
    as_of: date
    open_tasks: int
    task_risks: tuple[TaskRisk, ...]
    cycles: tuple[tuple[str, ...], ...]
    overloaded_owners: tuple[OwnerLoad, ...]
    data_issues: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "open_tasks": self.open_tasks,
            "task_risks": [asdict(r) for r in self.task_risks],
            "dependency_cycles": [list(c) for c in self.cycles],
            "overloaded_owners": [asdict(o) for o in self.overloaded_owners],
            "data_issues": list(self.data_issues),
        }


def natural_key(task_id: str) -> tuple:
    """Sort PLAT-3 before PLAT-12."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", task_id))


def analyze(tracker: Tracker, today: date, *, stale_after_days: int = 7,
            overload_threshold: int = 3, horizon_days: int = 7) -> RiskReport:
    tasks = tracker.tasks
    horizon = today + timedelta(days=horizon_days)
    dependents = _dependents(tasks)
    cycles = find_cycles(tasks)
    in_cycle = {task_id: cycle for cycle in cycles for task_id in cycle}
    problems = {t.id for t in tasks.values()
                if t.is_open and (t.status is Status.BLOCKED or _days_overdue(t, today) > 0)}

    risks: list[TaskRisk] = []
    for task in tasks.values():
        if not task.is_open:
            continue
        flags: list[str] = []
        reasons: list[str] = []

        days_overdue = _days_overdue(task, today)
        if days_overdue:
            flags.append("overdue")
            reasons.append(f"{days_overdue} day(s) past its due date ({task.due.isoformat()})")
        if task.status is Status.BLOCKED:
            flags.append("blocked")
            reasons.append("marked Blocked")

        waiting_on = tuple(sorted((upstream(task.id, tasks) & problems) - {task.id},
                                  key=natural_key))
        if waiting_on:
            flags.append("waiting_on_blocked")
            reasons.append(f"waiting on {', '.join(waiting_on)}, which is blocked or overdue")

        late = [d for d in task.depends_on if d in tasks and tasks[d].is_open and task.due
                and tasks[d].due and tasks[d].due >= task.due]
        if late:
            flags.append("due_before_dependency")
            reasons.append(f"due {task.due.isoformat()} but depends on "
                           + ", ".join(f"{d} (due {tasks[d].due.isoformat()})" for d in late))

        missing = [d for d in task.depends_on if d not in tasks]
        if missing:
            flags.append("missing_dependency")
            reasons.append(f"depends on {', '.join(missing)}, which is not in the tracker")

        if task.id in in_cycle:
            flags.append("in_cycle")
            reasons.append(f"part of a dependency cycle: {' -> '.join(in_cycle[task.id])} -> "
                           f"{in_cycle[task.id][0]}")

        if task.last_update and (today - task.last_update).days >= stale_after_days:
            flags.append("stale")
            reasons.append(f"no update for {(today - task.last_update).days} days")

        if not flags:
            continue
        affects = tuple(sorted((downstream(task.id, dependents) & _open_ids(tasks)) - {task.id},
                               key=natural_key))
        risks.append(TaskRisk(
            task_id=task.id, title=task.title, owner=task.owner, workstream=task.workstream,
            status=task.status.value, due=task.due.isoformat() if task.due else None,
            severity=_severity(task, flags, len(affects), horizon),
            flags=tuple(flags), reasons=tuple(reasons), days_overdue=days_overdue,
            impact=len(affects), affects=affects, waiting_on=waiting_on,
        ))

    risks.sort(key=lambda r: (_SEVERITY_RANK[r.severity], -r.impact, -r.days_overdue,
                              natural_key(r.task_id)))
    return RiskReport(
        as_of=today,
        open_tasks=len(_open_ids(tasks)),
        task_risks=tuple(risks),
        cycles=tuple(cycles),
        overloaded_owners=_overloaded(tasks, horizon, overload_threshold),
        data_issues=tuple(tracker.issues),
    )


def upstream(task_id: str, tasks: dict[str, Task]) -> set[str]:
    """Every task this one transitively depends on (breadth-first over prerequisites)."""
    seen: set[str] = set()
    queue = deque(d for d in tasks[task_id].depends_on if d in tasks)
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(d for d in tasks[current].depends_on if d in tasks and d not in seen)
    return seen


def downstream(task_id: str, dependents: dict[str, list[str]]) -> set[str]:
    """Every task that transitively depends on this one."""
    seen: set[str] = set()
    queue = deque(dependents.get(task_id, ()))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(d for d in dependents.get(current, ()) if d not in seen)
    return seen


def find_cycles(tasks: dict[str, Task]) -> list[tuple[str, ...]]:
    """Dependency cycles, each listed once, starting from its smallest ID.

    Iterative depth-first search with white/grey/black colouring: reaching a grey node means
    the current path loops back on itself. Iterative, so a long chain can't hit Python's
    recursion limit.
    """
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(tasks, white)
    found: dict[frozenset[str], tuple[str, ...]] = {}
    for start in sorted(tasks, key=natural_key):
        if colour[start] != white:
            continue
        path: list[str] = []
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, edge = stack.pop()
            if edge == 0:
                colour[node] = grey
                path.append(node)
            prereqs = [d for d in tasks[node].depends_on if d in tasks]
            if edge < len(prereqs):
                stack.append((node, edge + 1))
                nxt = prereqs[edge]
                if colour[nxt] == white:
                    stack.append((nxt, 0))
                elif colour[nxt] == grey:
                    cycle = path[path.index(nxt):]
                    first = min(range(len(cycle)), key=lambda i: natural_key(cycle[i]))
                    found.setdefault(frozenset(cycle), tuple(cycle[first:] + cycle[:first]))
            else:
                colour[node] = black
                path.pop()
    return sorted(found.values(), key=lambda c: natural_key(c[0]))


def _dependents(tasks: dict[str, Task]) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for task in tasks.values():
        for prereq in task.depends_on:
            if prereq in tasks:
                reverse[prereq].append(task.id)
    return reverse


def _open_ids(tasks: dict[str, Task]) -> set[str]:
    return {t.id for t in tasks.values() if t.is_open}


def _days_overdue(task: Task, today: date) -> int:
    if not task.is_open or task.due is None or task.due >= today:
        return 0
    return (today - task.due).days


def _severity(task: Task, flags: list[str], impact: int, horizon: date) -> str:
    if "in_cycle" in flags:
        return "critical"  # nothing in the cycle can ever finish
    if ("overdue" in flags or "blocked" in flags) and impact >= 2:
        return "critical"
    if {"overdue", "blocked", "due_before_dependency"} & set(flags):
        return "high"
    if "waiting_on_blocked" in flags and task.due and task.due <= horizon:
        return "high"
    return "medium"


def _overloaded(tasks: dict[str, Task], horizon: date, threshold: int) -> tuple[OwnerLoad, ...]:
    """Owners with `threshold`+ open tasks that are overdue or due within the horizon."""
    load: dict[str, list[str]] = defaultdict(list)
    for task in tasks.values():
        if task.is_open and task.owner and task.due and task.due <= horizon:
            load[task.owner].append(task.id)
    return tuple(OwnerLoad(owner, tuple(sorted(ids, key=natural_key)))
                 for owner, ids in sorted(load.items()) if len(ids) >= threshold)
