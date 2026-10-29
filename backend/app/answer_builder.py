"""Deterministic response construction from analytics results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .analytics import COUNT_METRICS
from .business_rules import dimension_label, metric_label
from .query_planner import QueryPlan
from .rule_based_interpreter import get_examples


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def format_money(value, currency_code: str = "") -> str:
    amount = Decimal(str(value))
    code = (currency_code or "").strip().upper()
    formatted = f"{amount:,.2f}"
    return f"{code} {formatted}" if code else formatted


def format_metric(metric: str, value, currency_code: str = "") -> str:
    if value is None:
        return "not available"
    if metric in COUNT_METRICS:
        return f"{int(value):,}"
    return format_money(value, currency_code)


def _metric_phrase(plan: QueryPlan) -> str:
    labels = [metric_label(metric) for metric in plan.metrics]
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _dimensions_phrase(plan: QueryPlan) -> str:
    return " and ".join(
        dimension_label(dimension) for dimension in plan.group_by
    )


def _period_suffix(date_range) -> str:
    if not date_range:
        return ""
    start = date_range.get("start")
    end = date_range.get("end")
    if start and end:
        return f" for {start} to {end}"
    if start:
        return f" from {start}"
    if end:
        return f" through {end}"
    return ""


def _filters_suffix(filters: list[dict]) -> str:
    if not filters:
        return ""
    parts = []
    for item in filters:
        field = dimension_label(item["field"])
        values = ", ".join(item["values"])
        if item["operator"] == "in":
            parts.append(f"{field} in ({values})")
        else:
            parts.append(f"{field} = {values}")
    return " for " + "; ".join(parts)


def _scope_text(plan: QueryPlan) -> str:
    if any(item.field == "status" for item in plan.filters):
        return "matching transactions"
    return "completed transactions"


def _month_label(value) -> str:
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%B %Y")
        except ValueError:
            return value
    return str(value)


def _coverage_text(dataset_summary: dict | None) -> str:
    if not dataset_summary:
        return ""
    coverage = dataset_summary.get("date_coverage") or {}
    start = coverage.get("start")
    end = coverage.get("end")
    if start and end:
        return f" Dataset coverage is {start} to {end}."
    return ""


def _no_data_answer(
    plan: QueryPlan,
    result: dict | None,
    dataset_summary: dict | None,
) -> str:
    date_range = result.get("date_range") if result else None
    filters = result.get("filters_applied", []) if result else []
    suffix = _period_suffix(date_range) + _filters_suffix(filters)
    answer = (
        f"No {_scope_text(plan)} match the selected period or filters"
        f"{suffix}."
    )
    return answer + _coverage_text(dataset_summary)


def _total_answer(
    plan: QueryPlan,
    result: dict,
    currency_code: str,
    dataset_summary: dict | None,
) -> str:
    if not result.get("has_data"):
        return _no_data_answer(plan, result, dataset_summary)

    count = int(result.get("row_count", 0))
    transaction_word = _plural(count, "transaction")
    suffix = _period_suffix(result.get("date_range")) + _filters_suffix(
        result.get("filters_applied", [])
    )
    reconciliation = result.get("reconciliation")

    if (
        plan.metrics == ["net_revenue"]
        and reconciliation
        and not any(item.field == "status" for item in plan.filters)
    ):
        answer = (
            f"Completed net revenue is "
            f"{format_money(reconciliation['net_revenue'], currency_code)} "
            f"across {count:,} completed {transaction_word}{suffix}, after "
            f"{format_money(reconciliation['discounts'], currency_code)} in "
            f"discounts on "
            f"{format_money(reconciliation['gross_sales'], currency_code)} in "
            "gross sales."
        )
        excluded_count = int(reconciliation.get("excluded_transaction_count", 0))
        if excluded_count:
            excluded_word = _plural(excluded_count, "transaction")
            excluded_verb = "is" if excluded_count == 1 else "are"
            answer += (
                f" {excluded_count:,} non-completed {excluded_word} totaling "
                f"{format_money(reconciliation['excluded_net_revenue'], currency_code)} "
                f"in net revenue {excluded_verb} excluded."
            )
        return answer

    scope = _scope_text(plan)
    if count == 1 and scope == "matching transactions":
        scope = "matching transaction"
    sentences = []
    for metric in plan.metrics:
        sentences.append(
            f"{metric_label(metric).capitalize()} is "
            f"{format_metric(metric, result['metrics'].get(metric), currency_code)} "
            f"across {count:,} {scope}{suffix}."
        )
    return " ".join(sentences)


def _grouped_answer(
    plan: QueryPlan,
    result: dict,
    currency_code: str,
    dataset_summary: dict | None,
) -> str:
    rows = result.get("supporting_data", [])
    if not rows:
        return _no_data_answer(plan, result, dataset_summary)

    metric = plan.metrics[0]
    dimensions = plan.group_by
    suffix = _period_suffix(result.get("date_range")) + _filters_suffix(
        result.get("filters_applied", [])
    )
    sort_field = plan.sort_by.field if plan.sort_by else metric
    sort_direction = plan.sort_by.direction if plan.sort_by else "desc"

    if len(rows) == 1:
        row = rows[0]
        if sort_field in plan.metrics:
            adjective = "highest" if sort_direction == "desc" else "lowest"
            sort_label = metric_label(sort_field)
        else:
            adjective = "first" if sort_direction == "asc" else "last"
            sort_label = dimension_label(sort_field)

        if len(dimensions) == 1:
            dimension = dimensions[0]
            first_metric = (
                f"{metric_label(metric)} "
                f"{format_metric(metric, row[metric], currency_code)}"
            )
            if sort_field == metric and len(plan.metrics) == 1:
                sentence = (
                    f"The {dimension_label(dimension)} with the {adjective} "
                    f"{sort_label} is {row[dimension]}, at "
                    f"{format_metric(metric, row[metric], currency_code)}"
                )
            else:
                sentence = (
                    f"The {dimension_label(dimension)} with the {adjective} "
                    f"{sort_label} is {row[dimension]}, with {first_metric}"
                )
        else:
            dimension_values = ", ".join(
                f"{dimension_label(dimension)} {row[dimension]}"
                for dimension in dimensions
            )
            sentence = (
                f"The {adjective} result is {dimension_values}, with "
                f"{metric_label(metric)} "
                f"{format_metric(metric, row[metric], currency_code)}"
            )

        other_metrics = [
            f"{metric_label(item)} {format_metric(item, row[item], currency_code)}"
            for item in plan.metrics[1:]
        ]
        if other_metrics:
            sentence += " and " + ", ".join(other_metrics)
        return sentence + suffix + "."

    if sort_field in plan.metrics:
        order_text = "highest first" if sort_direction == "desc" else "lowest first"
    else:
        order_text = (
            "in ascending order"
            if sort_direction == "asc"
            else "in descending order"
        )

    items = []
    for row in rows[:5]:
        dimension_values = ", ".join(
            str(row[dimension]) for dimension in dimensions
        )
        items.append(
            f"{dimension_values} "
            f"{format_metric(metric, row[metric], currency_code)}"
        )

    sentence = (
        f"{metric_label(metric).capitalize()} by {_dimensions_phrase(plan)}, "
        f"{order_text}: " + "; ".join(items)
    )
    if len(rows) > 5:
        sentence += f"; and {len(rows) - 5} more in the table"
    return sentence + suffix + "."


def _time_series_answer(
    plan: QueryPlan,
    result: dict,
    currency_code: str,
    dataset_summary: dict | None,
) -> str:
    rows = result.get("supporting_data", [])
    if not rows:
        return _no_data_answer(plan, result, dataset_summary)

    metric = plan.metrics[0]
    suffix = _period_suffix(result.get("date_range")) + _filters_suffix(
        result.get("filters_applied", [])
    )

    if len(rows) == 1:
        row = rows[0]
        return (
            f"Monthly {metric_label(metric)} for "
            f"{_month_label(row['order_month'])} is "
            f"{format_metric(metric, row[metric], currency_code)}{suffix}."
        )

    items = [
        f"{_month_label(row['order_month'])} "
        f"{format_metric(metric, row[metric], currency_code)}"
        for row in rows[:6]
    ]
    answer = (
        f"Monthly {metric_label(metric)}{suffix}: " + "; ".join(items)
    )
    if len(rows) > 6:
        answer += f"; and {len(rows) - 6} more months in the chart"
    return answer + "."


def _change_value_text(metric: str, value, currency_code: str) -> str:
    if metric in COUNT_METRICS:
        return f"{abs(int(value)):,}"
    return format_money(abs(Decimal(str(value))), currency_code)


def _compare_answer(
    plan: QueryPlan,
    result: dict,
    currency_code: str,
    dataset_summary: dict | None,
) -> str:
    if not result.get("has_data"):
        return _no_data_answer(plan, result, dataset_summary)

    periods = result.get("periods", [])
    changes = result.get("changes", [])
    if len(periods) < 2:
        return _no_data_answer(plan, result, dataset_summary)

    period_a = periods[0]
    period_b = periods[1]
    sentences = []
    for change in changes:
        metric = change["metric"]
        a_value = period_a["metrics"].get(metric)
        b_value = period_b["metrics"].get(metric)
        label = metric_label(metric).capitalize()

        if a_value is None or b_value is None:
            sentences.append(
                f"{label} could not be compared because one period has no "
                "value."
            )
            continue

        base = (
            f"{label} was {format_metric(metric, a_value, currency_code)} in "
            f"{period_a['label']} and "
            f"{format_metric(metric, b_value, currency_code)} in "
            f"{period_b['label']}"
        )
        absolute = change.get("absolute_change")
        percentage = change.get("percentage_change")

        if absolute is None:
            sentences.append(
                f"{base}; the absolute change is not available."
            )
            continue

        if Decimal(str(absolute)) > 0:
            movement = (
                "an increase of "
                f"{_change_value_text(metric, absolute, currency_code)}"
            )
        elif Decimal(str(absolute)) < 0:
            movement = (
                "a decrease of "
                f"{_change_value_text(metric, absolute, currency_code)}"
            )
        else:
            movement = "no change"

        if percentage is None:
            sentences.append(
                f"{base}; the percentage change is undefined because the "
                "baseline is zero."
            )
        else:
            sentences.append(
                f"{base}, {movement} ({Decimal(str(percentage)):.2f}%)."
            )

    if period_a.get("row_count", 0) == 0:
        sentences.append(
            f"No transactions were found for {period_a['label']}."
        )
    if period_b.get("row_count", 0) == 0:
        sentences.append(
            f"No transactions were found for {period_b['label']}."
        )

    answer = " ".join(sentences)
    filters = _filters_suffix(result.get("filters_applied", []))
    if filters:
        answer = answer.rstrip(".") + filters + "."
    return answer


def _visualization(plan: QueryPlan, result: dict) -> dict | None:
    if not result.get("has_data"):
        return None
    if plan.operation == "time_series" and plan.metrics:
        return {
            "type": "line",
            "x_key": "order_month",
            "y_key": plan.metrics[0],
            "title": f"{metric_label(plan.metrics[0]).capitalize()} by month",
        }
    if (
        plan.operation == "grouped_summary"
        and len(plan.group_by) == 1
        and len(plan.metrics) == 1
    ):
        return {
            "type": "bar",
            "x_key": plan.group_by[0],
            "y_key": plan.metrics[0],
            "title": (
                f"{metric_label(plan.metrics[0]).capitalize()} by "
                f"{dimension_label(plan.group_by[0])}"
            ),
        }
    if plan.operation == "compare_periods" and len(plan.metrics) == 1:
        return {
            "type": "bar",
            "x_key": "period",
            "y_key": plan.metrics[0],
            "title": (
                f"{metric_label(plan.metrics[0]).capitalize()} by period"
            ),
        }
    return None


def _suggestions(question: str) -> list[str]:
    return [
        example["question"]
        for example in get_examples()
        if example["question"].strip() != question.strip()
    ][:4]


def _warnings(
    plan: QueryPlan,
    result: dict,
    interpretation_warnings: tuple[str, ...],
    dataset_summary: dict | None,
) -> list[str]:
    warnings = []
    for warning in interpretation_warnings:
        if warning not in warnings:
            warnings.append(warning)
    for warning in result.get("warnings", []):
        if warning not in warnings:
            warnings.append(warning)

    status_filtered = any(item.field == "status" for item in plan.filters)
    if not status_filtered and "status" not in plan.group_by:
        warning = (
            "Completed transactions only; non-completed statuses are excluded "
            "from completed metrics."
        )
        if warning not in warnings:
            warnings.append(warning)

    if plan.date_range is None and plan.operation != "compare_periods":
        warning = (
            "No date range was specified in the question or filters; the "
            "result covers all available data."
        )
        if warning not in warnings:
            warnings.append(warning)

    if not result.get("has_data"):
        warning = "No matching transactions were found."
        if warning not in warnings:
            warnings.append(warning)
        coverage = _coverage_text(dataset_summary).strip()
        if coverage and coverage not in warnings:
            warnings.append(coverage)

    return warnings


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _status_response(
    plan: QueryPlan,
    source: str,
    interpretation_warnings: tuple[str, ...],
    question: str,
) -> dict:
    if plan.status == "needs_clarification":
        answer = plan.clarification_question or "Please clarify the question."
    else:
        answer = plan.unsupported_reason or "That analysis is not supported."

    return {
        "status": plan.status,
        "answer": answer,
        "metrics": {},
        "supporting_data": [],
        "calculation": "",
        "filters_applied": [],
        "date_range": None,
        "visualization": None,
        "warnings": list(interpretation_warnings),
        "suggestions": _suggestions(question),
        "metric_definitions": {},
        "interpretation_source": source,
        "has_data": False,
        "clarification_question": plan.clarification_question,
        "unsupported_reason": plan.unsupported_reason,
    }


def build_answer(
    plan: QueryPlan,
    result: dict | None,
    source: str,
    interpretation_warnings: tuple[str, ...] = (),
    currency_code: str = "",
    dataset_summary: dict | None = None,
    question: str = "",
) -> dict:
    if plan.status != "ready":
        return _status_response(
            plan, source, interpretation_warnings, question
        )

    if result is None:
        raise ValueError("an analytics result is required for a ready plan")

    operation = plan.operation
    if operation == "total":
        answer = _total_answer(plan, result, currency_code, dataset_summary)
    elif operation == "grouped_summary":
        answer = _grouped_answer(plan, result, currency_code, dataset_summary)
    elif operation == "time_series":
        answer = _time_series_answer(
            plan, result, currency_code, dataset_summary
        )
    elif operation == "compare_periods":
        answer = _compare_answer(
            plan, result, currency_code, dataset_summary
        )
    else:
        raise ValueError(f"unsupported operation: {operation}")

    response = {
        "status": "answered",
        "answer": answer,
        "metrics": result.get("metrics", {}) if operation == "total" else {},
        "supporting_data": result.get("supporting_data", []),
        "calculation": result.get("calculation", ""),
        "filters_applied": result.get("filters_applied", []),
        "date_range": result.get("date_range"),
        "visualization": _visualization(plan, result),
        "warnings": _warnings(
            plan, result, interpretation_warnings, dataset_summary
        ),
        "suggestions": _suggestions(question),
        "metric_definitions": result.get("metric_definitions", {}),
        "interpretation_source": source,
        "has_data": bool(result.get("has_data")),
    }

    if operation == "total" and result.get("reconciliation"):
        response["reconciliation"] = result["reconciliation"]
    if operation == "compare_periods":
        response["periods"] = result.get("periods", [])
        response["changes"] = result.get("changes", [])

    return _json_safe(response)
