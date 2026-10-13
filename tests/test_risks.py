from __future__ import annotations

from helpers import TODAY, row, tracker

from risk_agent.risks import analyze, find_cycles, natural_key
from risk_agent.tracker import parse_rows
from risk_agent.workspace import DemoWorkspace


def _by_id(report):
    return {r.task_id: r for r in report.task_risks}


def test_demo_report_ranks_the_blocked_root_cause_first():
    report = analyze(parse_rows(DemoWorkspace().read_sheet("demo-tracker").rows), TODAY)
    risks = _by_id(report)

    top = report.task_risks[0]
    assert top.task_id == "PAY-4"
    assert top.severity == "critical"
    assert set(top.flags) >= {"overdue", "blocked", "stale"}
    assert top.affects == ("PAY-5", "PAY-6", "PAY-7")
    assert top.days_overdue == 4

    assert risks["PAY-5"].waiting_on == ("PAY-4",)
    assert risks["ONB-14"].flags == ("missing_dependency",)
    assert report.cycles == (("PLAT-12", "PLAT-13"),)
    assert [(o.owner, o.task_ids) for o in report.overloaded_owners] == [
        ("Sneha", ("ONB-8", "ONB-9", "ONB-10", "ONB-11"))]
    assert "PLAT-1" not in risks  # done
    assert "PLAT-2" not in risks  # healthy


def test_done_tasks_are_never_risks():
    report = analyze(tracker(row("A-1", status="Done", due="2026-01-01", updated="2026-01-01")), TODAY)
    assert report.task_risks == ()
    assert report.open_tasks == 0


def test_overdue_counts_days_and_due_today_is_not_overdue():
    report = analyze(tracker(row("A-1", due="2026-10-10"), row("A-2", due="2026-10-13")), TODAY)
    risks = _by_id(report)
    assert risks["A-1"].days_overdue == 3
    assert "A-2" not in risks


def test_blocking_propagates_transitively_downstream():
    report = analyze(tracker(
        row("A-1", status="Blocked"),
        row("A-2", deps="A-1"),
        row("A-3", deps="A-2"),
        row("A-4", deps="A-3", status="Done"),
    ), TODAY)
    risks = _by_id(report)
    assert risks["A-1"].affects == ("A-2", "A-3")  # done A-4 isn't counted
    assert risks["A-1"].severity == "critical"     # blocked and holding up 2+ tasks
    assert risks["A-3"].waiting_on == ("A-1",)


def test_task_due_the_same_day_as_its_prerequisite_has_no_slack():
    report = analyze(tracker(row("A-1", due="2026-10-20"), row("A-2", due="2026-10-20", deps="A-1")), TODAY)
    assert "due_before_dependency" in _by_id(report)["A-2"].flags


def test_task_due_before_its_prerequisite_is_flagged():
    report = analyze(tracker(row("A-1", due="2026-10-20"), row("A-2", due="2026-10-18", deps="A-1")), TODAY)
    risk = _by_id(report)["A-2"]
    assert risk.flags == ("due_before_dependency",)
    assert risk.severity == "high"


def test_stale_boundary_is_inclusive():
    report = analyze(tracker(row("A-1", updated="2026-10-06"), row("A-2", updated="2026-10-07")), TODAY)
    risks = _by_id(report)
    assert "stale" in risks["A-1"].flags  # exactly 7 days
    assert "A-2" not in risks


def test_owner_overload_threshold_and_horizon():
    rows = [row(f"A-{i}", owner="Ravi", due="2026-10-15") for i in range(1, 3)]
    rows.append(row("A-9", owner="Ravi", due="2026-11-30"))  # outside the 7-day horizon
    assert analyze(tracker(*rows), TODAY).overloaded_owners == ()
    rows.append(row("A-3", owner="Ravi", due="2026-10-01"))  # overdue work counts too
    loads = analyze(tracker(*rows), TODAY).overloaded_owners
    assert [(o.owner, o.task_ids) for o in loads] == [("Ravi", ("A-1", "A-2", "A-3"))]


def test_three_task_cycle_is_found_once_from_its_smallest_id():
    t = tracker(row("C-3", deps="C-1"), row("C-1", deps="C-2"), row("C-2", deps="C-3"),
                row("D-1", deps="C-1"))
    assert find_cycles(t.tasks) == [("C-1", "C-2", "C-3")]


def test_long_chains_do_not_hit_the_recursion_limit():
    rows = [row("N-0")] + [row(f"N-{i}", deps=f"N-{i - 1}") for i in range(1, 3000)]
    assert find_cycles(tracker(*rows).tasks) == []


def test_ranking_is_severity_then_impact_then_days_overdue():
    report = analyze(tracker(
        row("A-1", due="2026-10-12"),                         # high: overdue, 1 day
        row("A-2", due="2026-10-01"),                         # high: overdue, 12 days
        row("A-3", updated="2026-09-01"),                     # medium: stale
        row("A-4", status="Blocked"),                         # critical: blocks A-5 and A-6
        row("A-5", deps="A-4", due="2026-11-05"), row("A-6", deps="A-5", due="2026-11-10"),
    ), TODAY)
    assert [r.task_id for r in report.task_risks][:3] == ["A-4", "A-2", "A-1"]


def test_natural_sort():
    assert sorted(["PLAT-12", "PLAT-3", "PAY-10"], key=natural_key) == ["PAY-10", "PLAT-3", "PLAT-12"]


def test_report_serialises_to_json_friendly_dict():
    report = analyze(parse_rows(DemoWorkspace().read_sheet("demo-tracker").rows), TODAY)
    d = report.to_dict()
    assert d["as_of"] == "2026-10-13"
    assert d["dependency_cycles"] == [["PLAT-12", "PLAT-13"]]
    assert d["task_risks"][0]["task_id"] == "PAY-4"
