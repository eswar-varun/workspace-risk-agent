"""Policy enforced in code around every tool call: an allowlist and an audit trail.

The prompt tells the model to stay within its sources, but prompts can be overridden: by a
confused model, or by instructions planted in a document it reads. So the allowlist is
checked in an ADK before-tool callback, which runs before the tool and can refuse it. A
refused call never reaches the tool, the connector or Google's APIs.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

audit_logger = logging.getLogger("risk_agent.audit")

# Tool arguments that name a file. Any value in these must be on the allowlist.
FILE_ARGUMENTS = ("sheet_id", "doc_id")

BeforeTool = Callable[[Any, dict[str, Any], Any], dict[str, Any] | None]
AfterTool = Callable[[Any, dict[str, Any], Any, dict[str, Any]], dict[str, Any] | None]


def make_guardrails(allowed_ids: frozenset[str]) -> tuple[BeforeTool, AfterTool]:
    started: dict[str, float] = {}

    def before_tool(tool: Any, args: dict[str, Any], tool_context: Any) -> dict[str, Any] | None:
        call_id = getattr(tool_context, "function_call_id", None) or ""
        requested = {name: args[name] for name in FILE_ARGUMENTS if name in args}
        refused = {name: value for name, value in requested.items()
                   if str(value) not in allowed_ids}
        if refused:
            _audit(tool, args, tool_context, decision="refused",
                   reason=f"not on the allowlist: {sorted(map(str, refused.values()))}")
            return {"error": ("Access refused: "
                              + ", ".join(f"{v!r}" for v in refused.values())
                              + " is not one of this agent's allowed sources. "
                                "Call list_sources to see what it may read.")}
        started[call_id] = time.perf_counter()
        _audit(tool, args, tool_context, decision="allowed")
        return None

    def after_tool(tool: Any, args: dict[str, Any], tool_context: Any,
                   tool_response: dict[str, Any]) -> dict[str, Any] | None:
        call_id = getattr(tool_context, "function_call_id", None) or ""
        began = started.pop(call_id, None)
        failed = isinstance(tool_response, dict) and "error" in tool_response
        _audit(tool, args, tool_context, decision="completed",
               outcome="error" if failed else "ok",
               duration_ms=round((time.perf_counter() - began) * 1000, 1) if began else None)
        return None  # never alter the result, only record it

    return before_tool, after_tool


def _audit(tool: Any, args: dict[str, Any], tool_context: Any, **fields: Any) -> None:
    record = {
        "tool": getattr(tool, "name", str(tool)),
        "agent": getattr(tool_context, "agent_name", None),
        "invocation_id": getattr(tool_context, "invocation_id", None),
        "call_id": getattr(tool_context, "function_call_id", None),
        "args": {k: v for k, v in args.items()},
        **{k: v for k, v in fields.items() if v is not None},
    }
    audit_logger.info(json.dumps(record, default=str, separators=(",", ":")))
