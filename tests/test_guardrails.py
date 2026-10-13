from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from risk_agent.guardrails import make_guardrails

ALLOWED = frozenset({"sheet-ok", "doc-ok"})


def _ctx(call_id="call-1"):
    return SimpleNamespace(agent_name="tracker_analyst", invocation_id="inv-1", function_call_id=call_id)


def _tool(name):
    return SimpleNamespace(name=name)


def _audit(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "risk_agent.audit"]


def test_allowlisted_file_is_allowed_and_audited(caplog):
    caplog.set_level(logging.INFO, logger="risk_agent.audit")
    before, after = make_guardrails(ALLOWED)

    assert before(_tool("get_project_risks"), {"sheet_id": "sheet-ok"}, _ctx()) is None
    assert after(_tool("get_project_risks"), {"sheet_id": "sheet-ok"}, _ctx(), {"task_risks": []}) is None

    allowed, completed = _audit(caplog)
    assert allowed["decision"] == "allowed"
    assert allowed["agent"] == "tracker_analyst"
    assert completed["decision"] == "completed"
    assert completed["outcome"] == "ok"
    assert completed["duration_ms"] >= 0


def test_file_outside_the_allowlist_is_refused_before_the_tool_runs(caplog):
    caplog.set_level(logging.INFO, logger="risk_agent.audit")
    before, _ = make_guardrails(ALLOWED)

    result = before(_tool("search_notes"), {"doc_id": "ceo-salaries", "query": "x"}, _ctx())

    assert "Access refused" in result["error"]
    assert "'ceo-salaries'" in result["error"]
    (record,) = _audit(caplog)
    assert record["decision"] == "refused"
    assert "ceo-salaries" in record["reason"]


def test_tools_without_file_arguments_pass_through():
    before, _ = make_guardrails(ALLOWED)
    assert before(_tool("list_sources"), {}, _ctx()) is None
    assert before(_tool("tracker_analyst"), {"request": "what's at risk?"}, _ctx()) is None


def test_every_file_argument_is_checked():
    before, _ = make_guardrails(ALLOWED)
    result = before(_tool("hypothetical"), {"sheet_id": "sheet-ok", "doc_id": "nope"}, _ctx())
    assert "'nope'" in result["error"]


def test_tool_errors_are_audited_as_errors(caplog):
    caplog.set_level(logging.INFO, logger="risk_agent.audit")
    before, after = make_guardrails(ALLOWED)
    before(_tool("get_task"), {"sheet_id": "sheet-ok"}, _ctx("c9"))
    after(_tool("get_task"), {"sheet_id": "sheet-ok"}, _ctx("c9"), {"error": "task not found"})
    assert _audit(caplog)[-1]["outcome"] == "error"
