"""Deterministic analytics engine driven only by validated query plans."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import Date, Integer, Numeric, distinct, func, select
from sqlalchemy.orm import Session

from .business_rules import (
    COMPLETED_STATUS,
    MONEY_QUANT,
    dimension_label,
    metric_definition,
    metric_label,
)
from .models import SalesTransaction
from .query_planner import (
    MAX_RESULT_LIMIT,
    Comparison,
    Filter,
    Period,
    QueryPlan,
    SortBy,
)

COUNT_METRICS = {"transaction_count", "units_sold"}
MONEY_METRICS = {
    "net_revenue",
    "gross_sales",
    "total_discounts",
    "average_order_value",
}
ALL_METRICS: tuple[str, ...] = (
    "net_revenue",
    "gross_sales",
    "total_discounts",
    "transaction_count",
    "units_sold",
    "average_order_value",
)
PERCENT_QUANT = Decimal("0.01")


def _month_expression(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        return func.strftime("%Y-%m-01", SalesTransaction.order_date)
    return func.date_trunc("month", SalesTransaction.order_date).cast(Date)


def _dimension_expression(session: Session, dimension: str):
    if dimension == "order_month":
        return _month_expression(session)
    return getattr(SalesTransaction, dimension)


def _metric_expression(metric: str):
    gross = SalesTransaction.quantity * SalesTransaction.unit_price
    net = gross - SalesTransaction.discount_amount

    if metric == "net_revenue":
        return func.coalesce(func.sum(net), 0).cast(Numeric(14, 2))
    if metric == "gross_sales":
        return func.coalesce(func.sum(gross), 0).cast(Numeric(14, 2))
    if metric == "total_discounts":
        return func.coalesce(func.sum(SalesTransaction.discount_amount), 0).cast(
            Numeric(14, 2)
        )
    if metric == "transaction_count":
        return func.count(distinct(SalesTransaction.transaction_id))
    if metric == "units_sold":
        return func.coalesce(func.sum(SalesTransaction.quantity), 0).cast(Integer)
    if metric == "average_order_value":
        return (
            func.sum(net)
            / func.nullif(
                func.count(distinct(SalesTransaction.transaction_id)), 0
            )
        ).cast(Numeric(14, 2))
    raise ValueError(f"unsupported metric: {metric}")


def _metric_expressions(metrics: list[str]):
    return [_metric_expression(metric).label(metric) for metric in metrics]


def _filter_conditions(filters: list[Filter]):
    conditions = []
    for filter_item in filters:
        column = getattr(SalesTransaction, filter_item.field)
        lowered = func.lower(column)
        values = [value.lower() for value in filter_item.values]
        if filter_item.operator == "eq":
            conditions.append(lowered == values[0])
        else:
            conditions.append(lowered.in_(values))
    return conditions


def _date_conditions(plan: QueryPlan):
    if plan.date_range is None:
        return []
    conditions = []
    if plan.date_range.start is not None:
        conditions.append(SalesTransaction.order_date >= plan.date_range.start)
    if plan.date_range.end is not None:
        conditions.append(SalesTransaction.order_date <= plan.date_range.end)
    return conditions


def _base_conditions(plan: QueryPlan):
    conditions = _filter_conditions(plan.filters) + _date_conditions(plan)
    has_status_filter = any(item.field == "status" for item in plan.filters)
    if not has_status_filter and "status" not in plan.group_by:
        conditions.append(SalesTransaction.status == COMPLETED_STATUS)
    return conditions


def _status_scope(plan: QueryPlan) -> str:
    has_status_filter = any(item.field == "status" for item in plan.filters)
    if has_status_filter:
        return "transactions matching the status filter"
    if "status" in plan.group_by:
        return "transactions grouped by status"
    return "completed transactions"


def _serialize_dimension(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _serialize_metric(metric: str, value: Any) -> Any:
    if value is None:
        return None
    if metric in COUNT_METRICS:
        return int(value)
    return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _filters_payload(plan: QueryPlan) -> list[dict[str, Any]]:
    return [
        {
            "field": item.field,
            "operator": item.operator,
            "values": list(item.values),
        }
        for item in plan.filters
    ]


def _date_range_payload(plan: QueryPlan) -> dict[str, str | None] | None:
    if plan.date_range is None:
        return None
    return {
        "start": (
            plan.date_range.start.isoformat()
            if plan.date_range.start
            else None
        ),
        "end": (
            plan.date_range.end.isoformat() if plan.date_range.end else None
        ),
    }


def _aggregate_total(
    session: Session, metrics: list[str], conditions: list[Any]
) -> tuple[dict[str, Any], int]:
    expressions = _metric_expressions(metrics)
    statement = (
        select(*expressions, func.count().label("_row_count"))
        .select_from(SalesTransaction)
        .where(*conditions)
    )
    row = session.execute(statement).one()
    mapping = row._mapping
    values = {
        metric: _serialize_metric(metric, mapping[metric]) for metric in metrics
    }
    return values, int(mapping["_row_count"] or 0)


def _order_terms(
    plan: QueryPlan,
    dimension_expressions: list[Any],
    metric_expressions: list[Any],
):
    metric_map = dict(zip(plan.metrics, metric_expressions))
    dimension_map = dict(zip(plan.group_by, dimension_expressions))

    if plan.operation == "time_series":
        return [dimension_expressions[0].asc()]

    if plan.sort_by is not None:
        field = plan.sort_by.field
        direction = plan.sort_by.direction
    elif "order_month" in dimension_map:
        field = "order_month"
        direction = "asc"
    else:
        field = plan.metrics[0]
        direction = "desc"

    expression = metric_map.get(field)
    if expression is None:
        expression = dimension_map.get(field)
    if expression is None:
        raise ValueError(f"cannot sort by unselected field: {field}")

    primary = expression.asc() if direction == "asc" else expression.desc()
    return [primary, *[expr.asc() for expr in dimension_expressions]]


def _execute_total(plan: QueryPlan, session: Session) -> dict[str, Any]:
    conditions = _base_conditions(plan)
    metrics, row_count = _aggregate_total(session, plan.metrics, conditions)
    scope = _status_scope(plan)

    return {
        "operation": "total",
        "metrics": metrics,
        "supporting_data": [],
        "row_count": row_count,
        "has_data": row_count > 0,
        "filters_applied": _filters_payload(plan),
        "date_range": _date_range_payload(plan),
        "calculation": (
            f"{', '.join(metric_label(m) for m in plan.metrics)} "
            f"across {scope}."
        ),
        "metric_definitions": {
            metric: metric_definition(metric, scope) for metric in plan.metrics
        },
        "warnings": [],
    }


def _execute_grouped(plan: QueryPlan, session: Session) -> dict[str, Any]:
    conditions = _base_conditions(plan)
    dimension_expressions = [
        _dimension_expression(session, dimension)
        for dimension in plan.group_by
    ]
    metric_expressions = _metric_expressions(plan.metrics)

    select_expressions = [
        expression.label(dimension)
        for dimension, expression in zip(
            plan.group_by, dimension_expressions
        )
    ] + metric_expressions

    limit = min(plan.limit, MAX_RESULT_LIMIT)
    statement = (
        select(*select_expressions)
        .select_from(SalesTransaction)
        .where(*conditions)
        .group_by(*dimension_expressions)
        .order_by(*_order_terms(plan, dimension_expressions, metric_expressions))
        .limit(limit)
    )

    rows = session.execute(statement).mappings().all()
    supporting_data = []
    for row in rows:
        item = {
            dimension: _serialize_dimension(row[dimension])
            for dimension in plan.group_by
        }
        item.update(
            {
                metric: _serialize_metric(metric, row[metric])
                for metric in plan.metrics
            }
        )
        supporting_data.append(item)

    scope = _status_scope(plan)
    dimensions_text = ", ".join(
        dimension_label(dimension) for dimension in plan.group_by
    )
    sort_field = (
        plan.sort_by.field
        if plan.sort_by
        else ("order_month" if "order_month" in plan.group_by else plan.metrics[0])
    )
    sort_direction = (
        plan.sort_by.direction
        if plan.sort_by
        else ("asc" if "order_month" in plan.group_by else "desc")
    )

    return {
        "operation": "grouped_summary",
        "group_by": list(plan.group_by),
        "metrics": plan.metrics,
        "supporting_data": supporting_data,
        "row_count": len(supporting_data),
        "has_data": bool(supporting_data),
        "limit": limit,
        "filters_applied": _filters_payload(plan),
        "date_range": _date_range_payload(plan),
        "calculation": (
            f"{', '.join(metric_label(m) for m in plan.metrics)} grouped by "
            f"{dimensions_text} across {scope}, sorted by "
            f"{sort_field} {sort_direction}."
        ),
        "metric_definitions": {
            metric: metric_definition(metric, scope) for metric in plan.metrics
        },
        "warnings": [],
    }


def _execute_time_series(plan: QueryPlan, session: Session) -> dict[str, Any]:
    conditions = _base_conditions(plan)
    month_expression = _month_expression(session)
    metric_expressions = _metric_expressions(plan.metrics)
    limit = min(plan.limit, MAX_RESULT_LIMIT)

    statement = (
        select(month_expression.label("order_month"), *metric_expressions)
        .select_from(SalesTransaction)
        .where(*conditions)
        .group_by(month_expression)
        .order_by(month_expression.asc())
        .limit(limit)
    )

    rows = session.execute(statement).mappings().all()
    supporting_data = []
    for row in rows:
        item = {"order_month": _serialize_dimension(row["order_month"])}
        item.update(
            {
                metric: _serialize_metric(metric, row[metric])
                for metric in plan.metrics
            }
        )
        supporting_data.append(item)

    scope = _status_scope(plan)
    return {
        "operation": "time_series",
        "group_by": ["order_month"],
        "metrics": plan.metrics,
        "supporting_data": supporting_data,
        "row_count": len(supporting_data),
        "has_data": bool(supporting_data),
        "limit": limit,
        "filters_applied": _filters_payload(plan),
        "date_range": _date_range_payload(plan),
        "calculation": (
            f"{', '.join(metric_label(m) for m in plan.metrics)} grouped by "
            f"calendar month across {scope}, in chronological order."
        ),
        "metric_definitions": {
            metric: metric_definition(metric, scope) for metric in plan.metrics
        },
        "warnings": [
            "Only months with matching transactions are shown; missing months "
            "are not assumed to be zero."
        ],
    }


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _serialize_change(metric: str, value: Decimal | None) -> Any:
    if value is None:
        return None
    if metric in COUNT_METRICS:
        return int(value)
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _execute_compare(plan: QueryPlan, session: Session) -> dict[str, Any]:
    comparison = plan.comparison
    if comparison is None:
        raise ValueError("compare_periods requires comparison periods")

    status_filtered = any(item.field == "status" for item in plan.filters)
    base_conditions = _filter_conditions(plan.filters)
    if not status_filtered:
        base_conditions.append(
            SalesTransaction.status == COMPLETED_STATUS
        )

    def period_conditions(period: Period):
        return [
            *base_conditions,
            SalesTransaction.order_date >= period.start,
            SalesTransaction.order_date <= period.end,
        ]

    a_metrics, a_count = _aggregate_total(
        session, plan.metrics, period_conditions(comparison.period_a)
    )
    b_metrics, b_count = _aggregate_total(
        session, plan.metrics, period_conditions(comparison.period_b)
    )

    changes = []
    warnings = []
    for metric in plan.metrics:
        a_value = a_metrics.get(metric)
        b_value = b_metrics.get(metric)
        if a_value is None or b_value is None:
            absolute = None
            percentage = None
            baseline_zero = False
        else:
            a_decimal = _to_decimal(a_value)
            b_decimal = _to_decimal(b_value)
            absolute = b_decimal - a_decimal
            baseline_zero = a_decimal == 0
            if baseline_zero:
                percentage = None
            else:
                percentage = (
                    (b_decimal - a_decimal) / a_decimal * Decimal("100")
                ).quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)

        changes.append(
            {
                "metric": metric,
                "absolute_change": _serialize_change(metric, absolute),
                "percentage_change": percentage,
                "baseline_zero": baseline_zero,
            }
        )

    if a_count == 0:
        warnings.append(
            f"No transactions found for {comparison.period_a.label}."
        )
    if b_count == 0:
        warnings.append(
            f"No transactions found for {comparison.period_b.label}."
        )
    if any(change["baseline_zero"] for change in changes):
        warnings.append(
            "Percentage change is undefined because the baseline period value "
            "is zero."
        )

    scope = _status_scope(plan)
    return {
        "operation": "compare_periods",
        "metrics": plan.metrics,
        "periods": [
            {
                "label": comparison.period_a.label,
                "start": comparison.period_a.start.isoformat(),
                "end": comparison.period_a.end.isoformat(),
                "metrics": a_metrics,
                "row_count": a_count,
                "has_data": a_count > 0,
            },
            {
                "label": comparison.period_b.label,
                "start": comparison.period_b.start.isoformat(),
                "end": comparison.period_b.end.isoformat(),
                "metrics": b_metrics,
                "row_count": b_count,
                "has_data": b_count > 0,
            },
        ],
        "changes": changes,
        "supporting_data": [
            {
                "period": comparison.period_a.label,
                **a_metrics,
            },
            {
                "period": comparison.period_b.label,
                **b_metrics,
            },
        ],
        "row_count": a_count + b_count,
        "has_data": a_count > 0 or b_count > 0,
        "filters_applied": _filters_payload(plan),
        "date_range": None,
        "calculation": (
            f"{', '.join(metric_label(m) for m in plan.metrics)} for "
            f"{comparison.period_a.label} and {comparison.period_b.label} "
            f"across {scope}; absolute change = period B − period A, and "
            "percentage change = (B − A) / A × 100 when A is non-zero."
        ),
        "metric_definitions": {
            metric: metric_definition(metric, scope) for metric in plan.metrics
        },
        "warnings": warnings,
    }


def execute_plan(plan: QueryPlan, session: Session) -> dict[str, Any]:
    if plan.status != "ready" or plan.operation is None:
        raise ValueError("only ready query plans can be executed")

    if plan.operation == "total":
        return _execute_total(plan, session)
    if plan.operation == "grouped_summary":
        return _execute_grouped(plan, session)
    if plan.operation == "time_series":
        return _execute_time_series(plan, session)
    if plan.operation == "compare_periods":
        return _execute_compare(plan, session)
    raise ValueError(f"unsupported operation: {plan.operation}")


def get_total_revenue(
    session: Session,
    filters: list[Filter] | None = None,
    date_range=None,
) -> dict[str, Any]:
    plan = QueryPlan(
        operation="total",
        metrics=list(ALL_METRICS),
        filters=filters or [],
        date_range=date_range,
    )
    conditions = _base_conditions(plan)
    metrics, row_count = _aggregate_total(session, list(ALL_METRICS), conditions)

    status_filtered = any(item.field == "status" for item in plan.filters)
    reconciliation = None
    if not status_filtered:
        excluded_conditions = (
            _filter_conditions(plan.filters)
            + _date_conditions(plan)
            + [SalesTransaction.status != COMPLETED_STATUS]
        )
        excluded_metrics, excluded_count = _aggregate_total(
            session,
            ["net_revenue", "gross_sales", "total_discounts", "transaction_count"],
            excluded_conditions,
        )
        reconciliation = {
            "gross_sales": metrics["gross_sales"],
            "discounts": metrics["total_discounts"],
            "net_revenue": metrics["net_revenue"],
            "excluded_gross_sales": excluded_metrics["gross_sales"],
            "excluded_net_revenue": excluded_metrics["net_revenue"],
            "excluded_transaction_count": excluded_metrics["transaction_count"],
            "excluded_rows": excluded_count,
        }

    return {
        "operation": "total",
        "metrics": metrics,
        "reconciliation": reconciliation,
        "supporting_data": [],
        "row_count": row_count,
        "has_data": row_count > 0,
        "filters_applied": _filters_payload(plan),
        "date_range": _date_range_payload(plan),
        "calculation": (
            "Completed net revenue = completed gross sales − completed "
            "discounts; non-completed statuses are excluded from completed "
            "metrics and reported separately."
        ),
        "metric_definitions": {
            metric: metric_definition(metric) for metric in ALL_METRICS
        },
        "warnings": [],
    }


def get_top_product_by_revenue(session: Session, limit: int = 1) -> dict[str, Any]:
    plan = QueryPlan(
        operation="grouped_summary",
        metrics=["net_revenue"],
        group_by=["product"],
        sort_by=SortBy(field="net_revenue", direction="desc"),
        limit=min(max(limit, 1), MAX_RESULT_LIMIT),
    )
    return execute_plan(plan, session)


def get_monthly_revenue_trend(
    session: Session, limit: int = MAX_RESULT_LIMIT
) -> dict[str, Any]:
    plan = QueryPlan(
        operation="time_series",
        metrics=["net_revenue"],
        limit=min(max(limit, 1), MAX_RESULT_LIMIT),
    )
    return execute_plan(plan, session)


def get_sales_by_region(
    session: Session, limit: int = MAX_RESULT_LIMIT
) -> dict[str, Any]:
    plan = QueryPlan(
        operation="grouped_summary",
        metrics=["net_revenue"],
        group_by=["region"],
        sort_by=SortBy(field="net_revenue", direction="desc"),
        limit=min(max(limit, 1), MAX_RESULT_LIMIT),
    )
    return execute_plan(plan, session)


def compare_monthly_revenue(
    session: Session, period_a: Period, period_b: Period
) -> dict[str, Any]:
    plan = QueryPlan(
        operation="compare_periods",
        metrics=["net_revenue"],
        comparison=Comparison(period_a=period_a, period_b=period_b),
    )
    return execute_plan(plan, session)


def _date_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def get_dataset_summary(session: Session) -> dict[str, Any]:
    row_count = session.execute(
        select(func.count()).select_from(SalesTransaction)
    ).scalar_one()
    min_date, max_date = session.execute(
        select(
            func.min(SalesTransaction.order_date),
            func.max(SalesTransaction.order_date),
        )
    ).one()
    status_rows = session.execute(
        select(SalesTransaction.status, func.count())
        .group_by(SalesTransaction.status)
        .order_by(SalesTransaction.status)
    ).all()
    status_counts = {
        str(status): int(count) for status, count in status_rows
    }

    zero_quantity = session.execute(
        select(func.count())
        .select_from(SalesTransaction)
        .where(SalesTransaction.quantity == 0)
    ).scalar_one()
    zero_price = session.execute(
        select(func.count())
        .select_from(SalesTransaction)
        .where(SalesTransaction.unit_price == 0)
    ).scalar_one()

    warnings = []
    if zero_quantity:
        warnings.append(
            f"{int(zero_quantity)} zero-quantity transaction(s) retained."
        )
    returned = status_counts.get("returned", 0)
    if returned:
        warnings.append(
            f"{returned} returned transaction(s) are excluded from completed "
            "revenue."
        )
    non_completed = sum(
        count
        for status, count in status_counts.items()
        if status != COMPLETED_STATUS
    )
    if non_completed and not returned:
        warnings.append(
            f"{non_completed} non-completed transaction(s) are excluded from "
            "completed revenue."
        )
    if zero_price:
        warnings.append(
            f"{int(zero_price)} transaction(s) have a zero unit price."
        )

    return {
        "row_count": int(row_count),
        "date_coverage": {
            "start": _date_string(min_date),
            "end": _date_string(max_date),
        },
        "status_counts": status_counts,
        "data_quality_warnings": warnings,
    }
