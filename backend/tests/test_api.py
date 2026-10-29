from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai_interpreter import (
    AIInterpreterError,
    interpret_question,
)
from app.config import Settings
from app.query_planner import QueryPlan


def test_total_revenue_endpoint_uses_database_figures(client):
    response = client.post(
        "/api/ask",
        json={"question": "What is the total revenue?", "preset_id": None},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["has_data"] is True
    assert data["metrics"]["net_revenue"] == pytest.approx(635.0)
    assert data["metrics"]["gross_sales"] == pytest.approx(650.0)
    assert data["metrics"]["total_discounts"] == pytest.approx(15.0)
    assert data["reconciliation"]["excluded_net_revenue"] == pytest.approx(100.0)
    assert "635.00" in data["answer"]
    assert data["interpretation_source"] == "rules"


def test_required_presets_work_without_groq(client):
    preset_ids = [
        "total_revenue",
        "top_product_revenue",
        "monthly_revenue_trend",
        "top_region_revenue",
        "compare_jan_feb",
    ]

    for preset_id in preset_ids:
        response = client.post(
            "/api/ask",
            json={"question": "", "preset_id": preset_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "answered", preset_id
        assert data["has_data"] is True, preset_id
        assert data["interpretation_source"] == "preset", preset_id


def test_ambiguous_question_needs_clarification(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "How did revenue change between two months?",
            "preset_id": None,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "needs_clarification"
    assert "Which two months" in data["answer"]
    assert data["has_data"] is False


def test_unsupported_question_is_explained(client):
    response = client.post(
        "/api/ask",
        json={"question": "What is the profit margin?", "preset_id": None},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unsupported"
    assert "cost data" in data["answer"]
    assert data["has_data"] is False


def test_empty_period_returns_no_data_with_coverage(client):
    response = client.post(
        "/api/ask",
        json={"question": "What is the total revenue in 2025?", "preset_id": None},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["has_data"] is False
    assert "No completed transactions match" in data["answer"]
    assert "2026-01-05 to 2026-05-01" in data["answer"]
    assert any("No matching transactions" in item for item in data["warnings"])


def test_zero_baseline_is_explained_in_answer(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "How did revenue change between March and April?",
            "preset_id": None,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["has_data"] is True
    assert data["changes"][0]["baseline_zero"] is True
    assert data["changes"][0]["percentage_change"] is None
    assert "undefined because the baseline is zero" in data["answer"]


def test_unknown_preset_is_rejected_safely(client):
    response = client.post(
        "/api/ask",
        json={"question": "", "preset_id": "drop_table"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unsupported"
    assert "not a recognized preset" in data["answer"]


def test_request_rejects_raw_sql_field(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is the total revenue?",
            "sql": "SELECT * FROM sales_transactions",
        },
    )

    assert response.status_code == 422

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(
            {
                "operation": "total",
                "metrics": ["net_revenue"],
                "sql": "SELECT * FROM sales_transactions",
            }
        )


def test_question_length_is_bounded(client):
    response = client.post(
        "/api/ask",
        json={"question": "x" * 501, "preset_id": None},
    )

    assert response.status_code == 422


def test_missing_groq_key_uses_rule_based_fallback():
    settings = Settings(
        database_url="sqlite+pysqlite://",
        database_admin_url="sqlite+pysqlite://",
        groq_api_key="",
        groq_model="",
        frontend_url="http://localhost:5173",
        currency_code="",
    )

    result = interpret_question("What is the total revenue?", settings=settings)

    assert result.source == "rules"
    assert result.warnings == ()
    assert result.plan.status == "ready"
    assert result.plan.operation == "total"


def test_groq_failure_uses_rule_based_fallback(monkeypatch):
    from app import ai_interpreter

    settings = Settings(
        database_url="sqlite+pysqlite://",
        database_admin_url="sqlite+pysqlite://",
        groq_api_key="test-key",
        groq_model="test-model",
        frontend_url="http://localhost:5173",
        currency_code="",
    )

    def fail(*args, **kwargs):
        raise AIInterpreterError("simulated failure")

    monkeypatch.setattr(ai_interpreter, "interpret_with_ai", fail)

    result = interpret_question("What is the total revenue?", settings=settings)

    assert result.source == "rules"
    assert any("Groq interpretation was unavailable" in item for item in result.warnings)
    assert result.plan.status == "ready"
    assert result.plan.operation == "total"


def test_overrides_region_filter_scopes_results(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is the total revenue?",
            "preset_id": None,
            "overrides": {
                "filters": [
                    {"field": "region", "operator": "eq", "values": ["North"]}
                ]
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["metrics"]["net_revenue"] == pytest.approx(335.0)
    assert {"field": "region", "operator": "eq", "values": ["North"]} in [
        {"field": f["field"], "operator": f["operator"], "values": f["values"]}
        for f in data["filters_applied"]
    ]


def test_overrides_date_range_scopes_results(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is the total revenue?",
            "preset_id": None,
            "overrides": {
                "date_range": {"start": "2026-01-01", "end": "2026-01-31"}
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["metrics"]["net_revenue"] == pytest.approx(290.0)
    assert data["date_range"] == {"start": "2026-01-01", "end": "2026-01-31"}


def test_question_date_range_takes_precedence_over_filter(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is the total revenue in January 2026?",
            "preset_id": None,
            "overrides": {
                "date_range": {"start": "2026-02-01", "end": "2026-02-28"}
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["metrics"]["net_revenue"] == pytest.approx(290.0)
    assert data["date_range"] == {
        "start": "2026-01-01",
        "end": "2026-01-31",
    }
    assert any(
        "question" in item.lower() and "ignored" in item.lower()
        for item in data["warnings"]
    )


def test_question_dimension_takes_precedence_over_filter(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is revenue by product in North?",
            "preset_id": None,
            "overrides": {
                "filters": [
                    {"field": "region", "operator": "eq", "values": ["South"]}
                ]
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert {
        row["product"]: row["net_revenue"] for row in data["supporting_data"]
    } == {"Widget": 190.0, "Gadget": 145.0}
    assert any(
        "region" in item.lower() and "ignored" in item.lower()
        for item in data["warnings"]
    )


def test_filter_bar_fills_a_different_dimension(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is the total revenue in January 2026?",
            "preset_id": None,
            "overrides": {
                "filters": [
                    {"field": "region", "operator": "eq", "values": ["North"]}
                ]
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["metrics"]["net_revenue"] == pytest.approx(190.0)
    assert {"field": "region", "operator": "eq", "values": ["North"]} in [
        {"field": item["field"], "operator": item["operator"], "values": item["values"]}
        for item in data["filters_applied"]
    ]


def test_compare_periods_ignores_date_filter(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "How did revenue change between January and February?",
            "preset_id": None,
            "overrides": {
                "date_range": {"start": "2026-05-01", "end": "2026-05-31"}
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert [period["label"] for period in data["periods"]] == [
        "January 2026",
        "February 2026",
    ]
    assert any(
        "comparison periods" in item.lower() for item in data["warnings"]
    )


def test_missing_date_scope_is_reported(client):
    response = client.post(
        "/api/ask",
        json={"question": "What is the total revenue?", "preset_id": None},
    )

    assert response.status_code == 200
    data = response.json()
    assert any(
        "No date range" in item for item in data["warnings"]
    )


def test_bare_month_warns_about_default_year(test_settings):
    result = interpret_question("What is sales in June?", settings=test_settings)

    assert result.source == "rules"
    assert result.plan.status == "ready"
    assert result.plan.date_range is not None
    assert result.plan.date_range.start.isoformat() == "2026-06-01"
    assert any("No year" in item for item in result.warnings)


def test_overrides_reject_invalid_date_order(client):
    response = client.post(
        "/api/ask",
        json={
            "question": "What is the total revenue?",
            "preset_id": None,
            "overrides": {
                "date_range": {"start": "2026-06-01", "end": "2026-01-01"}
            },
        },
    )

    assert response.status_code == 422


def test_health_and_examples(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert health.json()["groq_configured"] is False

    examples = client.get("/api/examples")
    assert examples.status_code == 200
    preset_ids = {
        example["preset_id"] for example in examples.json()["examples"]
    }
    assert {
        "total_revenue",
        "top_product_revenue",
        "monthly_revenue_trend",
        "top_region_revenue",
        "compare_jan_feb",
    }.issubset(preset_ids)


def test_response_timing_and_plan_summary_fields(client):
    response = client.post(
        "/api/ask",
        json={"question": "What is the total revenue?", "preset_id": None},
    )
    assert response.status_code == 200
    data = response.json()
    assert "response_time_ms" in data
    assert isinstance(data["response_time_ms"], (int, float))
    assert data["response_time_ms"] >= 0
    assert "query_plan_summary" in data
    assert data["query_plan_summary"]["operation"] == "total"
    assert "interpretation_confidence" in data
    assert data["interpretation_confidence"] > 0
    assert "agent_execution_trace" in data
    assert len(data["agent_execution_trace"]) == 5


def test_export_csv_endpoint(client):
    response = client.post(
        "/api/export",
        json={"question": "Which product generated the highest revenue?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    csv_text = response.text
    assert "product" in csv_text or "net_revenue" in csv_text
    assert "Widget" in csv_text


def test_conversation_session_context(client):
    session_id = "test-session-123"
    # First turn: ask product question
    resp1 = client.post(
        "/api/ask",
        json={
            "question": "What is revenue by product?",
            "session_id": session_id,
            "overrides": {
                "filters": [
                    {"field": "region", "operator": "eq", "values": ["North"]}
                ]
            },
        },
    )
    assert resp1.status_code == 200

    # Check session status
    status_resp = client.get(f"/api/session/{session_id}")
    assert status_resp.status_code == 200
    session_data = status_resp.json()
    assert session_data["session_id"] == session_id
    assert session_data["turns"] == 1
    assert session_data["last_question"] == "What is revenue by product?"

    # Second turn: refinement question carrying over North filter
    resp2 = client.post(
        "/api/ask",
        json={
            "question": "Now what about by category?",
            "session_id": session_id,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    # Filter should be carried over
    filter_fields = [f["field"] for f in data2["filters_applied"]]
    assert "region" in filter_fields


def test_rate_limiter_protection(client, monkeypatch):
    from app import rate_limiter

    rate_limiter.reset_rate_limits()
    # Temporarily set max requests to 2
    monkeypatch.setattr(rate_limiter, "_MAX_REQUESTS_PER_MINUTE", 2)

    r1 = client.post("/api/ask", json={"question": "Total revenue"})
    assert r1.status_code == 200

    r2 = client.post("/api/ask", json={"question": "Total revenue"})
    assert r2.status_code == 200

    r3 = client.post("/api/ask", json={"question": "Total revenue"})
    assert r3.status_code == 429
    assert "Rate limit exceeded" in r3.json()["answer"]

    rate_limiter.reset_rate_limits()

