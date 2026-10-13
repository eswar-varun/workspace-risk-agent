from __future__ import annotations

from helpers import TODAY

from risk_agent.config import Settings
from risk_agent.tools import UNTRUSTED_NOTICE, Runtime, make_tools
from risk_agent.workspace import DemoWorkspace


def _tools():
    return make_tools(Runtime(Settings(today=TODAY), DemoWorkspace))


def test_list_sources_returns_only_configured_ids():
    assert _tools().list_sources() == {"tracker_sheet_ids": ["demo-tracker"],
                                       "meeting_notes_doc_ids": ["demo-notes"]}


def test_project_risks_include_source_and_ranked_risks():
    result = _tools().get_project_risks("demo-tracker")
    assert result["source"]["title"] == "Demo project tracker"
    assert result["task_risks"][0]["task_id"] == "PAY-4"
    assert result["as_of"] == "2026-10-13"


def test_workstream_filter_is_case_insensitive():
    result = _tools().get_project_risks("demo-tracker", "payments")
    assert {r["task_id"] for r in result["task_risks"]} == {"PAY-4", "PAY-5", "PAY-6", "PAY-7"}
    assert result["filtered_to_workstream"] == "payments"


def test_get_task_explains_the_chain():
    result = _tools().get_task("demo-tracker", "pay-7")
    assert result["task"]["id"] == "PAY-7"
    assert result["upstream"] == ["PAY-4", "PAY-5", "PAY-6", "PLAT-1", "PLAT-2", "PLAT-3"]
    assert result["downstream"] == []
    assert result["risk"]["waiting_on"] == ["PAY-4"]


def test_unknown_task_and_unreadable_sheet_are_errors_not_exceptions():
    tools = _tools()
    assert "not in the tracker" in tools.get_task("demo-tracker", "NOPE-1")["error"]
    assert "not found" in tools.get_project_risks("someone-else")["error"]


def test_search_notes_returns_citations_with_an_untrusted_content_notice():
    result = _tools().search_notes("demo-notes", "PAY-4")
    assert result["notice"] == UNTRUSTED_NOTICE
    first = result["matches"][0]
    assert {"doc_title", "url", "section", "snippet"} <= set(first)


def test_workspace_is_created_lazily():
    created = []

    def factory():
        created.append(True)
        return DemoWorkspace()

    tools = make_tools(Runtime(Settings(today=TODAY), factory))
    assert created == []  # building the tools touches nothing
    tools.list_sources()
    assert created == []  # neither does listing sources
    tools.get_project_risks("demo-tracker")
    assert created == [True]
