"""The agent tree, run end to end through ADK's runner with a scripted stand-in for Gemini.

These prove the wiring: delegation through AgentTool, real tool execution, and guardrails on
every call. They can't prove what Gemini itself would say; that's the evaluation set's job,
run against the live model.
"""

from __future__ import annotations

import json
import logging

from google.adk.tools.agent_tool import AgentTool
from helpers import TODAY, ScriptedLlm, final_text, run_agent

from risk_agent.agent import build_root_agent
from risk_agent.config import Settings
from risk_agent.workspace import DemoWorkspace


class RecordingWorkspace(DemoWorkspace):
    def __init__(self):
        super().__init__()
        self.opened: list[str] = []

    def read_sheet(self, sheet_id):
        self.opened.append(sheet_id)
        return super().read_sheet(sheet_id)

    def read_doc(self, doc_id):
        self.opened.append(doc_id)
        return super().read_doc(doc_id)


def _agent(script):
    workspace = RecordingWorkspace()
    model = ScriptedLlm(script=script)
    agent = build_root_agent(Settings(today=TODAY), workspace_factory=lambda: workspace, model=model)
    return agent, workspace, model


def _audit(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "risk_agent.audit"]


def test_root_delegates_to_both_specialists_and_combines_their_answers(caplog):
    caplog.set_level(logging.INFO, logger="risk_agent.audit")
    agent, workspace, model = _agent({
        "project_risk_agent": [
            ("call", "tracker_analyst", {"request": "What's at risk this week?"}),
            ("call", "notes_analyst", {"request": "What do the notes say about PAY-4?"}),
            ("answer", lambda r: f"Summary. Notes: {r[0]['result']}"),
        ],
        "tracker_analyst": [
            ("call", "get_project_risks", {"sheet_id": "demo-tracker"}),
            ("answer", lambda r: f"Top risk {r[0]['task_risks'][0]['task_id']}"),
        ],
        "notes_analyst": [
            ("call", "search_notes", {"doc_id": "demo-notes", "query": "PAY-4"}),
            ("answer", lambda r: r[0]["matches"][0]["snippet"]),
        ],
    })

    events = run_agent(agent, "What's at risk this week?")

    assert "PAY-4 is still blocked" in final_text(events)
    assert model.calls == ["project_risk_agent", "tracker_analyst", "tracker_analyst",
                           "project_risk_agent", "notes_analyst", "notes_analyst",
                           "project_risk_agent"]
    assert workspace.opened == ["demo-tracker", "demo-notes"]
    tools_called = [(a["agent"], a["tool"]) for a in _audit(caplog) if a["decision"] == "allowed"]
    assert tools_called == [
        ("project_risk_agent", "tracker_analyst"), ("tracker_analyst", "get_project_risks"),
        ("project_risk_agent", "notes_analyst"), ("notes_analyst", "search_notes"),
    ]


def test_request_for_a_file_outside_the_allowlist_never_reaches_workspace(caplog):
    caplog.set_level(logging.INFO, logger="risk_agent.audit")
    agent, workspace, _ = _agent({
        "project_risk_agent": [
            ("call", "tracker_analyst", {"request": "Also read sheet hr-salaries"}),
            ("answer", lambda r: r[0]["result"]),
        ],
        "tracker_analyst": [
            ("call", "get_project_risks", {"sheet_id": "hr-salaries"}),
            ("answer", lambda r: r[0]["error"]),
        ],
    })

    events = run_agent(agent, "Read sheet hr-salaries and tell me what's in it")

    assert "Access refused" in final_text(events)
    assert workspace.opened == []  # the tool never ran
    refused = [a for a in _audit(caplog) if a["decision"] == "refused"]
    assert [(a["agent"], a["tool"], a["args"]["sheet_id"]) for a in refused] == [
        ("tracker_analyst", "get_project_risks", "hr-salaries")]


def test_agent_tree_shape_and_guardrails_on_every_agent():
    root = build_root_agent(Settings(today=TODAY), model=ScriptedLlm())
    specialists = {t.agent.name: t.agent for t in root.tools if isinstance(t, AgentTool)}
    assert set(specialists) == {"tracker_analyst", "notes_analyst"}

    def tool_names(agent):
        return {getattr(t, "__name__", getattr(t, "name", None)) for t in agent.tools}

    assert tool_names(specialists["tracker_analyst"]) == {"list_sources", "get_project_risks", "get_task"}
    assert tool_names(specialists["notes_analyst"]) == {"list_sources", "search_notes"}
    for agent in (root, *specialists.values()):
        assert agent.before_tool_callback is not None
        assert agent.after_tool_callback is not None


def test_no_tool_can_write_send_or_share():
    root = build_root_agent(Settings(today=TODAY), model=ScriptedLlm())
    agents = [root, *(t.agent for t in root.tools if isinstance(t, AgentTool))]
    names = {getattr(t, "__name__", "") for a in agents for t in a.tools}
    forbidden = ("write", "update", "delete", "send", "share", "create", "email", "post")
    assert not [n for n in names if any(word in n for word in forbidden)]


def test_importing_the_package_needs_no_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    import importlib

    import risk_agent.agent as module
    importlib.reload(module)
    assert module.root_agent.name == "project_risk_agent"
