from __future__ import annotations

import json
from datetime import date

import pytest

from risk_agent.__main__ import main
from risk_agent.config import Settings


def test_demo_is_the_default_and_pins_demo_sources():
    s = Settings.from_env({})
    assert s.backend == "demo"
    assert s.allowed_ids() == {"demo-tracker", "demo-notes"}


def test_google_backend_reads_allowlist_from_env():
    s = Settings.from_env({"RISK_AGENT_BACKEND": "google", "RISK_AGENT_SHEET_IDS": "a, b,a",
                           "RISK_AGENT_DOC_IDS": "c", "RISK_AGENT_TODAY": "2026-10-13"})
    assert s.sheet_ids == ("a", "b")
    assert s.allowed_ids() == {"a", "b", "c"}
    assert s.today == date(2026, 10, 13)


def test_google_backend_without_sources_is_rejected():
    with pytest.raises(ValueError, match="needs RISK_AGENT_SHEET_IDS"):
        Settings.from_env({"RISK_AGENT_BACKEND": "google"})


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="must be 'demo' or 'google'"):
        Settings.from_env({"RISK_AGENT_BACKEND": "sharepoint"})


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("RISK_AGENT_BACKEND", "demo")
    monkeypatch.setenv("RISK_AGENT_TODAY", "2026-10-13")


def test_cli_risks_prints_the_ranked_report(demo_env, capsys):
    assert main(["risks"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[2].startswith("[CRITICAL] PAY-4")
    assert "[CYCLE   ] PLAT-12 -> PLAT-13 -> PLAT-12" in out


def test_cli_task_and_search_print_json(demo_env, capsys):
    assert main(["task", "PAY-7"]) == 0
    assert json.loads(capsys.readouterr().out)["task"]["id"] == "PAY-7"
    assert main(["search", "PAY-4"]) == 0
    assert json.loads(capsys.readouterr().out)["matches"]
