"""FastAPI endpoints for the QueryMind-AI application."""

from __future__ import annotations

import csv
import io
import logging
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .ai_interpreter import interpret_question
from .analytics import execute_plan, get_dataset_summary, get_total_revenue
from .answer_builder import build_answer
from .config import get_settings
from .conversation import (
    apply_conversation_context,
    get_or_create_session,
    update_session,
)
from .database import runtime_session
from .query_planner import (
    MAX_QUESTION_LENGTH,
    DateRange,
    Filter,
    QueryPlan,
)
from .rate_limiter import check_rate_limit
from .rule_based_interpreter import get_examples

logger = logging.getLogger(__name__)
router = APIRouter()


class AskOverrides(BaseModel):
    """Trusted, user-selected scope values from the filter bar.

    These fill gaps in the validated plan; they never override scope that the
    question already specifies. They reuse the same validated schema types as
    the plan, so no raw SQL or arbitrary plans can be injected.
    """

    model_config = ConfigDict(extra="forbid")

    date_range: DateRange | None = None
    filters: list[Filter] = Field(default_factory=list, max_length=8)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(default="", max_length=MAX_QUESTION_LENGTH)
    preset_id: str | None = Field(default=None, max_length=80)
    overrides: AskOverrides | None = None
    session_id: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def require_question_or_preset(self) -> "AskRequest":
        if not self.question.strip() and not (
            self.preset_id and self.preset_id.strip()
        ):
            raise ValueError("question or preset_id is required")
        return self


def _apply_overrides(
    plan: QueryPlan, overrides: AskOverrides | None
) -> tuple[QueryPlan, list[str]]:
    """Fill gaps in a plan with trusted filter-bar values.

    The question is the source of truth. A date range or dimension filter that
    the question already specifies is never overwritten by the filter bar. The
    returned notes explain any filter-bar value that was ignored so the user can
    see the effective scope.
    """
    if overrides is None or plan.status != "ready":
        return plan, []

    notes: list[str] = []
    update: dict = {}

    if overrides.filters:
        existing_by_field = {item.field: item for item in plan.filters}
        merged = list(plan.filters)
        ignored_fields: list[str] = []
        for new_filter in overrides.filters:
            current = existing_by_field.get(new_filter.field)
            if current is not None:
                same_scope = (
                    current.operator == new_filter.operator
                    and {value.lower() for value in current.values}
                    == {value.lower() for value in new_filter.values}
                )
                if not same_scope and new_filter.field not in ignored_fields:
                    ignored_fields.append(new_filter.field)
                continue
            merged.append(new_filter)
            existing_by_field[new_filter.field] = new_filter

        if ignored_fields:
            fields = ", ".join(
                field.replace("_", " ") for field in ignored_fields
            )
            notes.append(
                f"The question already specifies {fields}; the matching "
                "filter-bar value(s) were ignored."
            )
        if len(merged) > len(plan.filters):
            update["filters"] = merged

    if overrides.date_range is not None:
        start = overrides.date_range.start
        end = overrides.date_range.end
        if start is not None or end is not None:
            if plan.operation == "compare_periods":
                notes.append(
                    "The question specifies explicit comparison periods; the "
                    "filter-bar date range was ignored."
                )
            elif plan.date_range is not None:
                if (plan.date_range.start, plan.date_range.end) != (start, end):
                    notes.append(
                        "The question specifies a date range; the filter-bar "
                        "date range was ignored because the question is the "
                        "source of truth."
                    )
            else:
                update["date_range"] = DateRange(start=start, end=end)

    if not update:
        return plan, notes
    return plan.model_copy(update=update), notes


def _error_payload(message: str, response_time_ms: int = 0) -> dict:
    return {
        "status": "error",
        "answer": message,
        "metrics": {},
        "supporting_data": [],
        "calculation": "",
        "filters_applied": [],
        "date_range": None,
        "visualization": None,
        "warnings": [],
        "suggestions": [],
        "metric_definitions": {},
        "interpretation_source": "none",
        "interpretation_confidence": 0.0,
        "response_time_ms": response_time_ms,
        "has_data": False,
        "query_plan_summary": None,
        "agent_execution_trace": [],
    }


def _run_plan(plan: QueryPlan, session) -> dict:
    status_filtered = any(
        item.field == "status" for item in plan.filters
    )
    if (
        plan.operation == "total"
        and plan.metrics == ["net_revenue"]
        and not status_filtered
    ):
        return get_total_revenue(
            session, filters=plan.filters, date_range=plan.date_range
        )
    return execute_plan(plan, session)


@router.get("/health", response_model=None)
def health() -> dict | JSONResponse:
    settings = get_settings()
    try:
        with runtime_session() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning(
            "Health database check failed: %s", exc.__class__.__name__
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "unavailable",
                "groq_configured": settings.groq_configured,
            },
        )
    return {
        "status": "ok",
        "database": "ok",
        "groq_configured": settings.groq_configured,
        "groq_model_configured": bool(settings.groq_model.strip()),
        "currency_code": settings.currency_code.strip().upper() or None,
    }


@router.get("/dataset/summary", response_model=None)
def dataset_summary() -> dict | JSONResponse:
    try:
        with runtime_session() as session:
            return get_dataset_summary(session)
    except SQLAlchemyError as exc:
        logger.warning(
            "Dataset summary query failed: %s", exc.__class__.__name__
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "The analytics database is unavailable.",
            },
        )


@router.get("/examples")
def examples() -> dict:
    return {"examples": get_examples()}


def _plan_summary(plan: QueryPlan) -> dict:
    return {
        "status": plan.status,
        "operation": plan.operation,
        "metrics": list(plan.metrics) if plan.metrics else [],
        "group_by": list(plan.group_by) if plan.group_by else [],
        "filters": [
            {"field": f.field, "operator": f.operator, "values": list(f.values)}
            for f in plan.filters
        ],
        "date_range": (
            {
                "start": plan.date_range.start.isoformat() if plan.date_range.start else None,
                "end": plan.date_range.end.isoformat() if plan.date_range.end else None,
            }
            if plan.date_range
            else None
        ),
        "limit": plan.limit,
    }


def _agent_trace(source: str, operation: str | None) -> list[dict[str, str | int]]:
    return [
        {"step": 1, "name": "Intent Recognition", "detail": f"Vectorless interpretation via {source}"},
        {"step": 2, "name": "Plan Verification", "detail": f"Deterministic Pydantic validation (operation={operation})"},
        {"step": 3, "name": "SQL Synthesis", "detail": "Constructed parameterized SQLAlchemy AST"},
        {"step": 4, "name": "Secure Execution", "detail": "Executed in read-only transaction with statement timeout"},
        {"step": 5, "name": "Evidence Formatting", "detail": "Deterministic reconciliation and narrative generation"},
    ]


@router.post("/ask", response_model=None)
def ask(request: AskRequest, http_request: Request = None) -> dict | JSONResponse:
    start_time = time.monotonic()

    # Rate limiting check (per IP, 120 req/min)
    client_ip = http_request.client.host if (http_request and http_request.client) else "127.0.0.1"
    allowed, _ = check_rate_limit(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content=_error_payload("Rate limit exceeded. Please wait a moment before sending more queries.", 0),
        )

    settings = get_settings()
    question = request.question.strip()
    if not question and request.preset_id:
        question = next(
            (
                example["question"]
                for example in get_examples()
                if example["preset_id"] == request.preset_id.strip()
            ),
            "",
        )

    try:
        interpretation = interpret_question(
            question,
            preset_id=request.preset_id,
            settings=settings,
        )
    except Exception as exc:
        logger.warning(
            "Question interpretation failed: %s", exc.__class__.__name__
        )
        elapsed_ms = round((time.monotonic() - start_time) * 1000)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "The question could not be interpreted. Please try again.",
                response_time_ms=elapsed_ms,
            ),
        )

    plan, override_notes = _apply_overrides(
        interpretation.plan, request.overrides
    )
    plan, context_notes = apply_conversation_context(
        request.session_id, plan, question
    )
    combined_warnings = tuple(
        list(interpretation.warnings) + override_notes + context_notes
    )

    if plan.status != "ready":
        elapsed_ms = round((time.monotonic() - start_time) * 1000)
        response = build_answer(
            plan,
            None,
            source=interpretation.source,
            interpretation_warnings=combined_warnings,
            currency_code=settings.currency_code,
            question=question,
        )
        response["question"] = question
        response["response_time_ms"] = elapsed_ms
        response["interpretation_confidence"] = getattr(interpretation, "confidence", 0.8)
        response["query_plan_summary"] = _plan_summary(plan)
        response["agent_execution_trace"] = _agent_trace(interpretation.source, plan.operation)
        return response

    try:
        with runtime_session() as session:
            summary = get_dataset_summary(session)
            result = _run_plan(plan, session)
        elapsed_ms = round((time.monotonic() - start_time) * 1000)
        response = build_answer(
            plan,
            result,
            source=interpretation.source,
            interpretation_warnings=combined_warnings,
            currency_code=settings.currency_code,
            dataset_summary=summary,
            question=question,
        )
        response["question"] = question
        response["response_time_ms"] = elapsed_ms
        response["interpretation_confidence"] = getattr(interpretation, "confidence", 0.95)
        response["query_plan_summary"] = _plan_summary(plan)
        response["agent_execution_trace"] = _agent_trace(interpretation.source, plan.operation)

        # Update conversation context for follow-up questions
        update_session(request.session_id, question, plan)

        logger.info(
            "Query answered in %sms [op=%s, source=%s]",
            elapsed_ms,
            plan.operation,
            interpretation.source,
        )
        return response
    except SQLAlchemyError as exc:
        logger.warning(
            "Analytics database query failed: %s", exc.__class__.__name__
        )
        elapsed_ms = round((time.monotonic() - start_time) * 1000)
        return JSONResponse(
            status_code=503,
            content=_error_payload(
                "The analytics database is unavailable. Please try again.",
                response_time_ms=elapsed_ms,
            ),
        )
    except Exception as exc:
        logger.warning(
            "Analytics request failed: %s", exc.__class__.__name__
        )
        elapsed_ms = round((time.monotonic() - start_time) * 1000)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "The analytics request failed. Please try again.",
                response_time_ms=elapsed_ms,
            ),
        )


@router.post("/export", response_model=None)
def export_csv(request: AskRequest, http_request: Request = None) -> Response:
    """Execute analytics plan and stream back the supporting data table as a downloadable CSV."""
    settings = get_settings()
    question = request.question.strip()
    if not question and request.preset_id:
        question = next(
            (
                example["question"]
                for example in get_examples()
                if example["preset_id"] == request.preset_id.strip()
            ),
            "",
        )

    interpretation = interpret_question(
        question,
        preset_id=request.preset_id,
        settings=settings,
    )
    plan, _ = _apply_overrides(interpretation.plan, request.overrides)
    if plan.status != "ready":
        return JSONResponse(
            status_code=400,
            content={"message": "Cannot export: query plan is not ready or unsupported."},
        )

    with runtime_session() as session:
        result = _run_plan(plan, session)

    rows = result.get("supporting_data", [])
    if not rows and result.get("metrics"):
        rows = [result["metrics"]]

    output = io.StringIO()
    if rows:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    else:
        writer = csv.writer(output)
        writer.writerow(["message"])
        writer.writerow(["No matching data found for export"])

    filename = f"sales_export_{int(time.time())}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/session/{session_id}")
def session_status(session_id: str) -> dict:
    session = get_or_create_session(session_id)
    if not session:
        return {"session_id": session_id, "turns": 0, "last_question": ""}
    return {
        "session_id": session.session_id,
        "turns": session.turn_count,
        "last_question": session.last_question,
        "last_plan": session.last_plan,
        "last_filters": session.last_filters,
    }
