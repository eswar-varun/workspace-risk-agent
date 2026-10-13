"""Settings, read from the environment so no configuration file ever holds a secret.

    RISK_AGENT_BACKEND    demo (default) or google
    RISK_AGENT_SHEET_IDS  comma-separated tracker sheet IDs the agent may read
    RISK_AGENT_DOC_IDS    comma-separated meeting-notes doc IDs the agent may read
    RISK_AGENT_MODEL      Gemini model (default below)
    RISK_AGENT_TODAY      pin "today" (YYYY-MM-DD) for reproducible demos and evaluations
    GOOGLE_APPLICATION_CREDENTIALS  service-account key file, for the google backend
    GEMINI_API_KEY / GOOGLE_API_KEY  read by the Gemini client, never by this code
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

DEFAULT_MODEL = "gemini-3.8-flash"
DEMO_TRACKER_ID = "demo-tracker"
DEMO_NOTES_ID = "demo-notes"


def _ids(value: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v.strip() for v in (value or "").split(",") if v.strip()))


@dataclass(frozen=True)
class Settings:
    backend: str = "demo"
    sheet_ids: tuple[str, ...] = (DEMO_TRACKER_ID,)
    doc_ids: tuple[str, ...] = (DEMO_NOTES_ID,)
    model: str = DEFAULT_MODEL
    today: date | None = None
    credentials_path: str | None = None
    stale_after_days: int = 7
    overload_threshold: int = 3
    horizon_days: int = 7
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.backend not in ("demo", "google"):
            raise ValueError(f"RISK_AGENT_BACKEND must be 'demo' or 'google', not {self.backend!r}")
        if self.backend == "google" and not (self.sheet_ids or self.doc_ids):
            raise ValueError(
                "the google backend needs RISK_AGENT_SHEET_IDS and/or RISK_AGENT_DOC_IDS")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        backend = env.get("RISK_AGENT_BACKEND", "demo").strip().lower() or "demo"
        demo = backend == "demo"
        today = env.get("RISK_AGENT_TODAY")
        return cls(
            backend=backend,
            sheet_ids=(DEMO_TRACKER_ID,) if demo else _ids(env.get("RISK_AGENT_SHEET_IDS")),
            doc_ids=(DEMO_NOTES_ID,) if demo else _ids(env.get("RISK_AGENT_DOC_IDS")),
            model=env.get("RISK_AGENT_MODEL") or DEFAULT_MODEL,
            today=date.fromisoformat(today) if today else None,
            credentials_path=env.get("GOOGLE_APPLICATION_CREDENTIALS"),
        )

    def allowed_ids(self) -> frozenset[str]:
        """The only files any tool may open. Enforced in code, not by the prompt."""
        return frozenset(self.sheet_ids) | frozenset(self.doc_ids)
