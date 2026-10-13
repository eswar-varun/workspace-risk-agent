"""Meeting notes: a document model shared by both connectors, plus retrieval with citations.

Retrieval here is lexical: exact task-ID matches dominate, then keyword overlap. For a few
pages of meeting notes that's precise and fully reproducible, and every result carries the
document title, link and section so the agent can cite it. Embeddings are the upgrade path
for large or paraphrase-heavy corpora.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TASK_ID = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")
MAX_SNIPPET = 400
_STOPWORDS = frozenset([
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was",
    "were", "be", "been", "it", "its", "this", "that", "what", "why", "how", "who", "when",
    "which", "about", "from", "at", "by", "as", "into", "than", "then", "there", "their",
    "they", "we", "our", "you", "your", "any", "all", "has", "have", "had", "not", "but",
    "did", "does", "do",
])


@dataclass(frozen=True)
class Section:
    heading: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    url: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Match:
    doc_title: str
    url: str
    section: str
    snippet: str
    score: int


def parse_markdown(text: str, *, doc_id: str, url: str = "") -> Document:
    """Headings (#) start sections; bullets and paragraphs become searchable passages."""
    title = ""
    sections: list[Section] = []
    heading, passages, current = "", [], []

    def flush_passage() -> None:
        if current:
            passages.append(" ".join(current))
            current.clear()

    def flush_section() -> None:
        flush_passage()
        if passages:
            sections.append(Section(heading, tuple(passages)))
            passages.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            text_ = line[level:].strip()
            if level == 1 and not title:
                title = text_
                continue
            flush_section()
            heading = text_
        elif not line:
            flush_passage()
        elif line.startswith(("- ", "* ")):
            flush_passage()
            current.append(line[2:].strip())
        else:
            current.append(line)  # continuation of the current bullet or paragraph
    flush_section()
    return Document(doc_id, title or doc_id, url, tuple(sections))


def search(doc: Document, query: str, limit: int = 5) -> list[Match]:
    ids = set(TASK_ID.findall(query.upper()))
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower())
             if len(w) > 2 and w not in _STOPWORDS}
    scored: list[tuple[int, int, Match]] = []
    order = 0
    for section in doc.sections:
        for passage in section.paragraphs:
            order += 1
            passage_ids = set(TASK_ID.findall(passage))
            passage_words = set(re.findall(r"[a-z0-9]+", passage.lower()))
            score = 10 * len(ids & passage_ids) + len(words & passage_words)
            if score:
                snippet = passage if len(passage) <= MAX_SNIPPET else passage[:MAX_SNIPPET] + "…"
                scored.append((score, order, Match(doc.title, doc.url, section.heading, snippet,
                                                   score)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [match for _, _, match in scored[:limit]]
