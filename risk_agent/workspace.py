"""Read-only access to the tracker sheet and meeting-notes docs.

Two implementations of one small interface:

- DemoWorkspace serves the files in demo/, so everything runs offline.
- GoogleWorkspace calls the Sheets and Docs APIs with read-only scopes. There is no write
  method anywhere in this module, so even a fully compromised prompt can't modify a file.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import DEMO_NOTES_ID, DEMO_TRACKER_ID
from .notes import Document, Section, parse_markdown

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"

# Least privilege: the agent can read spreadsheets and documents, nothing else.
SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
)


class WorkspaceError(Exception):
    """A source couldn't be read. The message is safe to show the user."""


@dataclass(frozen=True)
class Sheet:
    id: str
    title: str
    url: str
    rows: list[list[Any]]


class Workspace(Protocol):
    def read_sheet(self, sheet_id: str) -> Sheet: ...

    def read_doc(self, doc_id: str) -> Document: ...


class DemoWorkspace:
    def __init__(self, root: Path = DEMO_DIR) -> None:
        self._root = root

    def read_sheet(self, sheet_id: str) -> Sheet:
        if sheet_id != DEMO_TRACKER_ID:
            raise WorkspaceError(f"sheet {sheet_id!r} not found")
        with open(self._root / "tracker.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        return Sheet(sheet_id, "Demo project tracker", "demo/tracker.csv", rows)

    def read_doc(self, doc_id: str) -> Document:
        if doc_id != DEMO_NOTES_ID:
            raise WorkspaceError(f"document {doc_id!r} not found")
        text = (self._root / "meeting-notes.md").read_text(encoding="utf-8")
        return parse_markdown(text, doc_id=doc_id, url="demo/meeting-notes.md")


class GoogleWorkspace:
    def __init__(self, sheets_service: Any, docs_service: Any) -> None:
        self._sheets = sheets_service
        self._docs = docs_service

    @classmethod
    def from_service_account(cls, key_path: str) -> GoogleWorkspace:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            key_path, scopes=list(SCOPES))
        return cls(
            build("sheets", "v4", credentials=credentials, cache_discovery=False),
            build("docs", "v1", credentials=credentials, cache_discovery=False),
        )

    def read_sheet(self, sheet_id: str) -> Sheet:
        meta = _execute(
            self._sheets.spreadsheets().get(
                spreadsheetId=sheet_id, fields="properties.title,sheets.properties.title"),
            f"sheet {sheet_id}")
        tab = meta["sheets"][0]["properties"]["title"]
        values = _execute(
            self._sheets.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range=f"'{tab}'",
                # Dates as serial numbers: unambiguous, unlike locale-formatted strings.
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            ),
            f"sheet {sheet_id}")
        return Sheet(sheet_id, meta["properties"]["title"],
                     f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
                     values.get("values", []))

    def read_doc(self, doc_id: str) -> Document:
        doc = _execute(self._docs.documents().get(documentId=doc_id), f"document {doc_id}")
        return Document(doc_id, doc.get("title", doc_id),
                        f"https://docs.google.com/document/d/{doc_id}/edit",
                        tuple(_doc_sections(doc)))


def _doc_sections(doc: dict[str, Any]) -> list[Section]:
    """Turn a Docs API document into sections: headings start a section, paragraphs and
    bullets become passages. Tables and images are skipped."""
    sections: list[Section] = []
    heading, passages = "", []
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        text = "".join(run.get("textRun", {}).get("content", "")
                       for run in paragraph.get("elements", [])).strip()
        if not text:
            continue
        style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "")
        if style.startswith("HEADING") or style in ("TITLE", "SUBTITLE"):
            if passages:
                sections.append(Section(heading, tuple(passages)))
                passages = []
            heading = text
        else:
            passages.append(text)
    if passages:
        sections.append(Section(heading, tuple(passages)))
    return sections


def _execute(request: Any, what: str) -> dict[str, Any]:
    from googleapiclient.errors import HttpError

    try:
        return request.execute()
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status in (403, 404):
            raise WorkspaceError(
                f"{what} was not found or is not shared with the agent's service account "
                f"(HTTP {status}). Share it as Viewer with the service account's email."
            ) from exc
        raise WorkspaceError(f"Google API error reading {what} (HTTP {status})") from exc
