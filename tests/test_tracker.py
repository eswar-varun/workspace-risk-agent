from __future__ import annotations

from datetime import date

import pytest
from helpers import HEADER, row, tracker

from risk_agent.tracker import Status, TrackerError, parse_date, parse_rows
from risk_agent.workspace import DemoWorkspace


def test_demo_tracker_parses_cleanly():
    t = parse_rows(DemoWorkspace().read_sheet("demo-tracker").rows)
    assert len(t.tasks) == 14
    assert t.issues == []
    assert t.tasks["PAY-7"].depends_on == ("PAY-6", "PLAT-3")
    assert t.tasks["PAY-4"].status is Status.BLOCKED


@pytest.mark.parametrize(("value", "expected"), [
    ("2026-10-09", date(2026, 10, 9)),
    (46304, date(2026, 10, 9)),        # Google Sheets serial number
    ("46304", date(2026, 10, 9)),
    (46304.75, date(2026, 10, 9)),     # a date-time serial keeps only the date
    ("", None),
    (None, None),
])
def test_dates(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["10/9/2026", "9 Oct", True])
def test_ambiguous_or_invalid_dates_are_refused(value):
    with pytest.raises(ValueError):
        parse_date(value)


def test_header_aliases_and_column_order_are_flexible():
    t = parse_rows([["Status", "Key", "Summary", "Deadline"], ["Done", "A-1", "Ship it", "2026-10-01"]])
    task = t.tasks["A-1"]
    assert (task.title, task.status, task.due) == ("Ship it", Status.DONE, date(2026, 10, 1))


def test_missing_required_column_is_a_clear_error():
    with pytest.raises(TrackerError, match="missing required column.*status"):
        parse_rows([["ID", "Task"], ["A-1", "x"]])


def test_empty_sheet_is_an_error():
    with pytest.raises(TrackerError, match="empty"):
        parse_rows([])


def test_bad_rows_become_data_issues_not_crashes():
    t = tracker(
        row("A-1", status="Sort of done"),
        row("A-1"),
        ["", "orphan row", "", "", "", "", "", ""],
        row("A-2", due="10/12/2026"),
        ["", "", "", "", "", "", "", ""],
    )
    assert set(t.tasks) == {"A-1", "A-2"}
    assert t.tasks["A-1"].status is Status.NOT_STARTED
    assert t.tasks["A-2"].due is None
    assert len(t.issues) == 4
    assert any("unknown status" in i for i in t.issues)
    assert any("duplicate ID A-1" in i for i in t.issues)
    assert any("no task ID" in i for i in t.issues)
    assert any("A-2: due date ignored" in i for i in t.issues)


def test_dependencies_split_on_commas_semicolons_and_spaces():
    t = tracker(row("A-1", deps="B-1, B-2;B-3  B-1"))
    assert t.tasks["A-1"].depends_on == ("B-1", "B-2", "B-3")


def test_short_rows_are_padded():
    t = parse_rows([HEADER, ["A-1", "Short row", "", "", "Done"]])
    assert t.tasks["A-1"].due is None
