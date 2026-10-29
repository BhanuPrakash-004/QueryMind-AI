"""Conversation context manager for multi-turn analytical inquiries."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any

from .query_planner import Filter, QueryPlan

_SESSION_TTL_SECONDS = 900  # 15 minutes
_lock = Lock()


@dataclass
class ConversationSession:
    session_id: str
    last_question: str = ""
    last_plan: dict[str, Any] = field(default_factory=dict)
    last_filters: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    updated_at: float = field(default_factory=time.monotonic)


_sessions: dict[str, ConversationSession] = {}


def _purge_expired(now: float) -> None:
    expired = [sid for sid, s in _sessions.items() if (now - s.updated_at) > _SESSION_TTL_SECONDS]
    for sid in expired:
        _sessions.pop(sid, None)


def get_or_create_session(session_id: str | None) -> ConversationSession | None:
    if not session_id or not session_id.strip():
        return None
    cleaned_id = session_id.strip()
    now = time.monotonic()
    with _lock:
        _purge_expired(now)
        if cleaned_id not in _sessions:
            _sessions[cleaned_id] = ConversationSession(session_id=cleaned_id)
        return _sessions[cleaned_id]


def update_session(session_id: str | None, question: str, plan: QueryPlan) -> None:
    if not session_id or not session_id.strip():
        return
    cleaned_id = session_id.strip()
    now = time.monotonic()
    with _lock:
        session = _sessions.get(cleaned_id)
        if session is None:
            session = ConversationSession(session_id=cleaned_id)
            _sessions[cleaned_id] = session

        session.last_question = question
        session.last_plan = {
            "operation": plan.operation,
            "metrics": list(plan.metrics),
            "group_by": list(plan.group_by),
            "filters": [f.model_dump() for f in plan.filters],
        }
        session.last_filters = [f.model_dump() for f in plan.filters]
        session.turn_count += 1
        session.updated_at = now


def apply_conversation_context(
    session_id: str | None,
    plan: QueryPlan,
    question: str,
) -> tuple[QueryPlan, list[str]]:
    """Enrich a newly interpreted plan with previous conversation filters if relevant."""
    if not session_id or not session_id.strip():
        return plan, []

    cleaned_id = session_id.strip()
    with _lock:
        session = _sessions.get(cleaned_id)
        if not session or not session.last_plan:
            return plan, []

    notes: list[str] = []
    # If the user asks a follow-up without specifying filters, or is refining a previous query
    lowered = question.lower()
    is_refinement = any(
        kw in lowered
        for kw in ("also", "now", "only", "and", "filter by", "what about", "instead")
    )

    if is_refinement and session.last_filters and plan.operation != "compare_periods":
        existing_keys = {f.field for f in plan.filters}
        inherited = []
        for f_dict in session.last_filters:
            if f_dict["field"] not in existing_keys:
                try:
                    inherited.append(Filter.model_validate(f_dict))
                except Exception:
                    pass

        if inherited:
            updated_filters = list(plan.filters) + inherited
            plan = plan.model_copy(update={"filters": updated_filters})
            notes.append(
                f"Carried over {len(inherited)} filter(s) from previous turn in session {cleaned_id}."
            )

    return plan, notes


def clear_sessions() -> None:
    with _lock:
        _sessions.clear()
