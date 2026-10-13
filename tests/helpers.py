from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from datetime import date
from typing import Any

import httplib2
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import Field

from risk_agent import prompts
from risk_agent.tracker import Tracker, parse_rows

TODAY = date(2026, 10, 13)
HEADER = ["ID", "Task", "Workstream", "Owner", "Status", "Due", "Depends on", "Last update"]


def tracker(*rows: list[Any]) -> Tracker:
    return parse_rows([HEADER, *[list(r) for r in rows]])


def row(task_id: str, status: str = "In progress", due: str = "2026-10-30", deps: str = "",
        owner: str = "Asha", updated: str = "2026-10-12", workstream: str = "Core") -> list[str]:
    return [task_id, f"Task {task_id}", workstream, owner, status, due, deps, updated]


class RecordingHttp:
    """Stands in for httplib2.Http under googleapiclient: records requests, replays responses."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str]] = []

    def request(self, uri: str, method: str = "GET", body: Any = None, headers: Any = None,
                redirections: int = 5, connection_type: Any = None) -> tuple[Any, bytes]:
        self.requests.append((method, uri))
        status, payload = self.responses.pop(0)
        return httplib2.Response({"status": str(status)}), json.dumps(payload).encode()


AGENT_PROMPTS = {"project_risk_agent": prompts.ROOT, "tracker_analyst": prompts.TRACKER,
                 "notes_analyst": prompts.NOTES}


class ScriptedLlm(BaseLlm):
    """A stand-in for Gemini that follows a script per agent.

    Each step is ("call", tool_name, args) or ("answer", fn) where fn receives the latest
    function responses and returns the text to answer with. This exercises the real ADK
    runner, AgentTool delegation, callbacks and tools, without a network or an API key.
    """

    model: str = "scripted"
    script: dict[str, list[tuple]] = Field(default_factory=dict)
    calls: list[str] = Field(default_factory=list)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        system = str(llm_request.config.system_instruction or "")
        agent = next(name for name, prompt in AGENT_PROMPTS.items()
                     if system.startswith(prompt[:60]))
        self.calls.append(agent)
        step = self.script[agent].pop(0)
        if step[0] == "call":
            part = types.Part(function_call=types.FunctionCall(name=step[1], args=step[2]))
        else:
            responses = [p.function_response.response for p in llm_request.contents[-1].parts
                         if p.function_response]
            part = types.Part(text=step[1](responses))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def run_agent(agent: Any, message: str) -> list[Any]:
    async def go() -> list[Any]:
        runner = InMemoryRunner(agent=agent, app_name="test")
        session = await runner.session_service.create_session(app_name="test", user_id="u")
        content = types.Content(role="user", parts=[types.Part(text=message)])
        return [e async for e in runner.run_async(user_id="u", session_id=session.id,
                                                  new_message=content)]
    return asyncio.run(go())


def final_text(events: list[Any], author: str = "project_risk_agent") -> str:
    texts = [p.text for e in events if e.author == author and e.content
             for p in (e.content.parts or []) if p.text]
    return texts[-1] if texts else ""


Answer = Callable[[list[dict]], str]
