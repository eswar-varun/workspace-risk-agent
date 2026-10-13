"""The Google connector, tested offline: googleapiclient builds the real requests from its
bundled API definitions, and a recording HTTP layer replays canned responses."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from googleapiclient.discovery import build
from helpers import RecordingHttp

from risk_agent.workspace import SCOPES, DemoWorkspace, GoogleWorkspace, WorkspaceError

SHEET_META = {"properties": {"title": "Q4 tracker"}, "sheets": [{"properties": {"title": "Tasks"}}]}
SHEET_VALUES = {"values": [["ID", "Task", "Status", "Due"], ["PAY-4", "Sandbox", "Blocked", 46304]]}
DOC = {
    "title": "Weekly sync",
    "body": {"content": [
        {"sectionBreak": {}},
        {"paragraph": {"elements": [{"textRun": {"content": "Payments\n"}}],
                       "paragraphStyle": {"namedStyleType": "HEADING_2"}}},
        {"paragraph": {"elements": [{"textRun": {"content": "PAY-4 is "}},
                                    {"textRun": {"content": "still blocked.\n"}}],
                       "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "bullet": {}}},
        {"paragraph": {"elements": [{"textRun": {"content": "\n"}}]}},
        {"table": {}},
    ]},
}


def _workspace(responses):
    http = RecordingHttp(responses)
    return GoogleWorkspace(build("sheets", "v4", http=http), build("docs", "v1", http=http)), http


def test_scopes_are_read_only():
    assert all(scope.endswith(".readonly") for scope in SCOPES)


def test_read_sheet_asks_for_unformatted_serial_dates_and_parses_rows():
    ws, http = _workspace([(200, SHEET_META), (200, SHEET_VALUES)])

    sheet = ws.read_sheet("abc123")

    assert sheet.title == "Q4 tracker"
    assert sheet.url == "https://docs.google.com/spreadsheets/d/abc123/edit"
    assert sheet.rows[1] == ["PAY-4", "Sandbox", "Blocked", 46304]
    (_, meta_uri), (_, values_uri) = http.requests
    assert "/spreadsheets/abc123" in meta_uri
    query = parse_qs(urlparse(values_uri).query)
    assert query["valueRenderOption"] == ["UNFORMATTED_VALUE"]
    assert query["dateTimeRenderOption"] == ["SERIAL_NUMBER"]
    assert "Tasks" in values_uri


def test_read_doc_turns_headings_into_sections_and_joins_text_runs():
    ws, _ = _workspace([(200, DOC)])

    doc = ws.read_doc("doc9")

    assert doc.title == "Weekly sync"
    assert doc.url == "https://docs.google.com/document/d/doc9/edit"
    assert [(s.heading, s.paragraphs) for s in doc.sections] == [
        ("Payments", ("PAY-4 is still blocked.",))]


@pytest.mark.parametrize("status", [403, 404])
def test_unshared_or_missing_files_explain_how_to_fix_it(status):
    ws, _ = _workspace([(status, {"error": {"message": "nope"}})])
    with pytest.raises(WorkspaceError, match="not shared with the agent's service account"):
        ws.read_doc("doc9")


def test_other_api_errors_are_reported_with_status():
    ws, _ = _workspace([(500, {"error": {"message": "boom"}})])
    with pytest.raises(WorkspaceError, match="HTTP 500"):
        ws.read_sheet("abc123")


def test_demo_workspace_only_serves_its_own_files():
    ws = DemoWorkspace()
    assert ws.read_sheet("demo-tracker").title == "Demo project tracker"
    with pytest.raises(WorkspaceError):
        ws.read_sheet("someone-else")
    with pytest.raises(WorkspaceError):
        ws.read_doc("someone-else")
