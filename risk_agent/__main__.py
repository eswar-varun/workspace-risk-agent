"""Run the tools directly, without the model: useful for checking a live Workspace connection.

    python -m risk_agent risks [--workstream Payments] [--json]
    python -m risk_agent task PAY-7
    python -m risk_agent search "PAY-4 vendor"

Uses the same settings as the agent (RISK_AGENT_BACKEND, RISK_AGENT_SHEET_IDS, ...), the same
tool functions and the same allowlist, but no Gemini call, so it needs no API key.
"""

from __future__ import annotations

import argparse
import json
import sys

from .agent import default_workspace_factory
from .config import Settings
from .tools import Runtime, make_tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m risk_agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    commands = parser.add_subparsers(dest="command", required=True)
    risks = commands.add_parser("risks", help="the ranked risk report")
    risks.add_argument("--workstream", default="")
    task = commands.add_parser("task", help="one task's dependencies and risk")
    task.add_argument("task_id")
    find = commands.add_parser("search", help="search the meeting notes")
    find.add_argument("query")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    tools = make_tools(Runtime(settings, default_workspace_factory(settings)))
    if args.command == "risks":
        result = tools.get_project_risks(settings.sheet_ids[0], args.workstream)
    elif args.command == "task":
        result = tools.get_task(settings.sheet_ids[0], args.task_id)
    else:
        result = tools.search_notes(settings.doc_ids[0], args.query)

    if args.json or "error" in result or args.command != "risks":
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_risks(result)
    return 1 if "error" in result else 0


def _print_risks(report: dict) -> None:
    print(f"{report['source']['title']}: {report['open_tasks']} open tasks, "
          f"as of {report['as_of']}\n")
    for r in report["task_risks"]:
        print(f"[{r['severity'].upper():8}] {r['task_id']:8} {r['owner']:8} "
              f"{'; '.join(r['reasons'])}")
    for cycle in report["dependency_cycles"]:
        print(f"[CYCLE   ] {' -> '.join(cycle)} -> {cycle[0]}")
    for load in report["overloaded_owners"]:
        print(f"[OVERLOAD] {load['owner']}: {', '.join(load['task_ids'])} due within the horizon")
    for issue in report["data_issues"]:
        print(f"[DATA    ] {issue}")


if __name__ == "__main__":
    sys.exit(main())
