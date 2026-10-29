from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.analytics import (
    compare_monthly_revenue,
    execute_plan,
    get_monthly_revenue_trend,
    get_sales_by_region,
    get_top_product_by_revenue,
    get_total_revenue,
)
from app.business_rules import dataset_totals
from app.query_planner import DateRange, Period, QueryPlan, SortBy


def test_total_revenue_matches_independent_decimal_calculation(
    seeded_session, sample_rows
):
    expected = dataset_totals(sample_rows)
    result = get_total_revenue(seeded_session)

    assert result["metrics"]["net_revenue"] == expected["completed_net_revenue"]
    assert result["metrics"]["gross_sales"] == expected["completed_gross_sales"]
    assert (
        result["metrics"]["total_discounts"]
        == expected["completed_discounts"]
    )
    assert (
        result["metrics"]["transaction_count"]
        == expected["completed_transaction_count"]
    )
    assert result["metrics"]["units_sold"] == expected["units_sold"]
    assert (
        result["metrics"]["average_order_value"]
        == expected["average_order_value"]
    )
    assert result["metrics"]["net_revenue"] == Decimal("635.00")
    assert result["metrics"]["gross_sales"] == Decimal("650.00")
    assert result["metrics"]["total_discounts"] == Decimal("15.00")
    assert result["metrics"]["transaction_count"] == 6
    assert result["metrics"]["units_sold"] == 9
    assert result["metrics"]["average_order_value"] == Decimal("105.83")
    assert result["reconciliation"]["excluded_net_revenue"] == Decimal("100.00")
    assert result["reconciliation"]["excluded_transaction_count"] == 1


def test_highest_revenue_product(seeded_session):
    result = get_top_product_by_revenue(seeded_session)

    assert result["supporting_data"][0]["product"] == "Widget"
    assert result["supporting_data"][0]["net_revenue"] == Decimal("390.00")


def test_monthly_trend_is_chronological_and_missing_month_is_not_zero(
    seeded_session,
):
    result = get_monthly_revenue_trend(seeded_session)
    data = result["supporting_data"]

    assert [(row["order_month"], row["net_revenue"]) for row in data] == [
        ("2026-01-01", Decimal("290.00")),
        ("2026-02-01", Decimal("245.00")),
        ("2026-04-01", Decimal("0.00")),
        ("2026-05-01", Decimal("100.00")),
    ]
    assert all(row["order_month"] != "2026-03-01" for row in data)


def test_region_ranking(seeded_session):
    result = get_sales_by_region(seeded_session)

    assert [
        (row["region"], row["net_revenue"]) for row in result["supporting_data"]
    ] == [
        ("North", Decimal("335.00")),
        ("South", Decimal("200.00")),
        ("East", Decimal("100.00")),
        ("West", Decimal("0.00")),
    ]


def test_month_comparison_and_percentage_change(seeded_session):
    january = Period(label="January 2026", start="2026-01-01", end="2026-01-31")
    february = Period(
        label="February 2026", start="2026-02-01", end="2026-02-28"
    )

    result = compare_monthly_revenue(seeded_session, january, february)

    assert result["periods"][0]["metrics"]["net_revenue"] == Decimal("290.00")
    assert result["periods"][1]["metrics"]["net_revenue"] == Decimal("245.00")
    assert result["changes"][0]["absolute_change"] == Decimal("-45.00")
    assert result["changes"][0]["percentage_change"] == Decimal("-15.52")
    assert result["changes"][0]["baseline_zero"] is False


def test_zero_baseline_percentage_is_undefined(seeded_session):
    march = Period(label="March 2026", start="2026-03-01", end="2026-03-31")
    april = Period(label="April 2026", start="2026-04-01", end="2026-04-30")

    result = compare_monthly_revenue(seeded_session, march, april)

    assert result["has_data"] is True
    assert result["periods"][0]["row_count"] == 0
    assert result["periods"][1]["row_count"] == 1
    assert result["changes"][0]["baseline_zero"] is True
    assert result["changes"][0]["percentage_change"] is None
    assert "No transactions found for March 2026." in result["warnings"]


def test_empty_period_is_honest_no_data(seeded_session):
    january_2025 = Period(
        label="January 2025", start="2025-01-01", end="2025-01-31"
    )
    february_2025 = Period(
        label="February 2025", start="2025-02-01", end="2025-02-28"
    )

    result = compare_monthly_revenue(
        seeded_session, january_2025, february_2025
    )

    assert result["has_data"] is False
    assert result["periods"][0]["row_count"] == 0
    assert result["periods"][1]["row_count"] == 0
    assert result["changes"][0]["percentage_change"] is None
    assert "No transactions found for January 2025." in result["warnings"]
    assert "No transactions found for February 2025." in result["warnings"]


def test_grouping_by_status_does_not_force_completed_only(seeded_session):
    plan = QueryPlan(
        operation="grouped_summary",
        metrics=["net_revenue", "transaction_count"],
        group_by=["status"],
        sort_by=SortBy(field="status", direction="asc"),
    )

    result = execute_plan(plan, seeded_session)

    assert result["supporting_data"] == [
        {
            "status": "completed",
            "net_revenue": Decimal("635.00"),
            "transaction_count": 6,
        },
        {
            "status": "returned",
            "net_revenue": Decimal("100.00"),
            "transaction_count": 1,
        },
    ]


def test_date_filtered_total(seeded_session):
    plan = QueryPlan(
        operation="total",
        metrics=["net_revenue"],
        date_range=DateRange(start="2026-01-01", end="2026-01-31"),
    )

    result = execute_plan(plan, seeded_session)

    assert result["metrics"]["net_revenue"] == Decimal("290.00")
    assert result["row_count"] == 2


def test_query_plan_rejects_unbounded_or_invalid_plans():
    with pytest.raises(ValidationError):
        QueryPlan(
            operation="grouped_summary",
            metrics=["net_revenue"],
            group_by=["product"],
            limit=26,
        )

    with pytest.raises(ValidationError):
        QueryPlan(
            operation="total",
            metrics=["net_revenue"],
            date_range=DateRange(start="2026-02-01", end="2026-01-01"),
        )

    with pytest.raises(ValidationError):
        QueryPlan(
            operation="total",
            metrics=["net_revenue"],
            group_by=["product"],
        )
