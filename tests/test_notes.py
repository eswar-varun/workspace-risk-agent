from __future__ import annotations

from risk_agent.notes import MAX_SNIPPET, parse_markdown, search
from risk_agent.workspace import DemoWorkspace


def _demo():
    return DemoWorkspace().read_doc("demo-notes")


def test_markdown_becomes_titled_sections_of_passages():
    doc = _demo()
    assert doc.title == "Weekly delivery sync, 12 October 2026"
    assert [s.heading for s in doc.sections] == [
        "Payments", "Onboarding", "Platform", "Pasted from the vendor's email", "Action items"]
    # A bullet that wraps over two lines is one passage.
    assert doc.sections[0].paragraphs[0].endswith('"end of next week".')


def test_task_id_matches_rank_above_keyword_matches():
    matches = search(_demo(), "PAY-4 credentials")
    assert matches[0].section == "Payments"
    assert "PAY-4 is still blocked" in matches[0].snippet
    assert all("PAY-4" in m.snippet for m in matches[:2])


def test_query_case_does_not_matter_for_task_ids():
    assert search(_demo(), "pay-4")[0].section == "Payments"


def test_keyword_search_and_citation_fields():
    (first, *_) = search(_demo(), "security review")
    assert first.section == "Onboarding"
    assert first.doc_title == "Weekly delivery sync, 12 October 2026"
    assert first.url == "demo/meeting-notes.md"


def test_no_match_returns_nothing():
    assert search(_demo(), "kubernetes helm") == []


def test_stopwords_alone_match_nothing():
    assert search(_demo(), "what is the") == []


def test_long_passages_are_truncated():
    doc = parse_markdown("# T\n\n## S\n\n- " + "word " * 300, doc_id="d")
    (match,) = search(doc, "word")
    assert len(match.snippet) == MAX_SNIPPET + 1  # plus the ellipsis
