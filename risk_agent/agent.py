"""The ADK agents.

    project_risk_agent (root)
      ├─ tracker_analyst  → list_sources, get_project_risks, get_task
      └─ notes_analyst    → list_sources, search_notes

The root calls each specialist through AgentTool, so it gets their answers back and writes
the final response itself (rather than handing the conversation over with a transfer). The
same guardrail callbacks wrap every tool call on every agent.

`root_agent` is what `adk web` and `adk run` look for.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from . import prompts
from .config import Settings
from .guardrails import make_guardrails
from .tools import Runtime, make_tools
from .workspace import DemoWorkspace, GoogleWorkspace, Workspace


def default_workspace_factory(settings: Settings) -> Callable[[], Workspace]:
    def factory() -> Workspace:
        if settings.backend == "demo":
            return DemoWorkspace()
        if not settings.credentials_path:
            raise RuntimeError("the google backend needs GOOGLE_APPLICATION_CREDENTIALS set "
                               "to a service-account key file")
        return GoogleWorkspace.from_service_account(settings.credentials_path)
    return factory


def build_root_agent(settings: Settings | None = None, *,
                     workspace_factory: Callable[[], Workspace] | None = None,
                     model: Any = None) -> LlmAgent:
    """Build the agent tree. Tests pass a fake workspace and a scripted model."""
    settings = settings or Settings.from_env()
    runtime = Runtime(settings, workspace_factory or default_workspace_factory(settings))
    tools = make_tools(runtime)
    before_tool, after_tool = make_guardrails(settings.allowed_ids())
    model = model or settings.model
    guarded = {"before_tool_callback": before_tool, "after_tool_callback": after_tool}

    tracker_analyst = LlmAgent(
        name="tracker_analyst",
        model=model,
        description="Analyses the project tracker: risks, owners, due dates and dependencies.",
        instruction=prompts.TRACKER,
        tools=[tools.list_sources, tools.get_project_risks, tools.get_task],
        **guarded,
    )
    notes_analyst = LlmAgent(
        name="notes_analyst",
        model=model,
        description="Finds what meeting notes say about given tasks or topics, with citations.",
        instruction=prompts.NOTES,
        tools=[tools.list_sources, tools.search_notes],
        **guarded,
    )
    return LlmAgent(
        name="project_risk_agent",
        model=model,
        description="Finds and explains project risks from Google Sheets and Docs.",
        instruction=prompts.ROOT,
        tools=[AgentTool(tracker_analyst), AgentTool(notes_analyst)],
        **guarded,
    )


root_agent = build_root_agent()
