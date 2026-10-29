"""Small, understandable rule-based interpreter for key-free demo mode."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from .query_planner import (
    MAX_RESULT_LIMIT,
    Comparison,
    DateRange,
    Filter,
    Period,
    QueryPlan,
    SortBy,
)

DEFAULT_DATASET_YEAR = 2026

MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

MONTH_PATTERN = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\b(?:\s+((?:19|20)\d{2}))?", re.IGNORECASE
)
# Any plausible 4-digit year (1900-2099) is captured as a date range. Years
# outside this window (e.g. 2205, 0999) are treated as implausible and trigger
# a clarification instead of being silently ignored.
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
ANY_YEAR_PATTERN = re.compile(r"\b(\d{4})\b")
MIN_DATA_YEAR = 1900
MAX_DATA_YEAR = 2099
TOP_PATTERN = re.compile(r"\b(?:top|first|bottom)\s+(\d{1,2})\b", re.IGNORECASE)
RELATIVE_DATE_PATTERN = re.compile(
    r"\b(?:last|this|previous|next)\s+(?:month|quarter|year|week)\b",
    re.IGNORECASE,
)

REGION_VALUES = {"east", "north", "south", "west"}
CATEGORY_VALUES = {"accessories", "electronics", "furniture"}
CHANNEL_VALUES = {"online", "retail"}
STATUS_VALUES = {"completed", "returned", "cancelled", "canceled", "pending"}

DIMENSION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("product", "product"),
    ("products", "product"),
    ("category", "category"),
    ("categories", "category"),
    ("region", "region"),
    ("regions", "region"),
    ("channel", "sales_channel"),
    ("channels", "sales_channel"),
    ("month", "order_month"),
    ("monthly", "order_month"),
    ("status", "status"),
    ("statuses", "status"),
)

UNSUPPORTED_TERMS: dict[str, str] = {
    "profit": "Profit and margin require cost data that is not in the dataset.",
    "margin": "Profit and margin require cost data that is not in the dataset.",
    "cost": "Cost data is not in the dataset.",
    "forecast": "Forecasting is outside the supported analytics operations.",
    "predict": "Prediction is outside the supported analytics operations.",
    "customer": "Customer-level data is not in the dataset.",
    "inventory": "Inventory data is not in the dataset.",
    "stock": "Inventory data is not in the dataset.",
    "marketing": "Marketing attribution data is not in the dataset.",
    "campaign": "Marketing attribution data is not in the dataset.",
    "employee": "Employee data is not in the dataset.",
    "salary": "Employee data is not in the dataset.",
    "sql": "The assistant does not execute user-written SQL.",
    "database": "The assistant does not expose direct database access.",
    "drop table": "Destructive database operations are not supported.",
    "delete": "Destructive database operations are not supported.",
    "insert": "Database write operations are not supported.",
    "update": "Database write operations are not supported.",
    "share of total": "Share-of-total is not implemented in this version.",
    "percentage of total": "Share-of-total is not implemented in this version.",
    "average price": "Average price is not a supported metric.",
    "return rate": "Return rate is not a supported metric.",
    "churn": "Customer churn data is not in the dataset.",
    "conversion": "Conversion data is not in the dataset.",
    "why": "The assistant reports data, not causal explanations.",
}


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    question: str
    plan: QueryPlan


PRESETS: dict[str, Preset] = {
    "total_revenue": Preset(
        id="total_revenue",
        label="Total revenue",
        question="What is the total revenue?",
        plan=QueryPlan(
            operation="total",
            metrics=["net_revenue"],
        ),
    ),
    "top_product_revenue": Preset(
        id="top_product_revenue",
        label="Top product",
        question="Which product generated the highest revenue?",
        plan=QueryPlan(
            operation="grouped_summary",
            metrics=["net_revenue"],
            group_by=["product"],
            sort_by=SortBy(field="net_revenue", direction="desc"),
            limit=1,
        ),
    ),
    "monthly_revenue_trend": Preset(
        id="monthly_revenue_trend",
        label="Monthly trend",
        question="What is the monthly revenue trend?",
        plan=QueryPlan(
            operation="time_series",
            metrics=["net_revenue"],
            limit=MAX_RESULT_LIMIT,
        ),
    ),
    "top_region_revenue": Preset(
        id="top_region_revenue",
        label="Top region",
        question="Which region generated the highest sales?",
        plan=QueryPlan(
            operation="grouped_summary",
            metrics=["net_revenue"],
            group_by=["region"],
            sort_by=SortBy(field="net_revenue", direction="desc"),
            limit=1,
        ),
    ),
    "compare_jan_feb": Preset(
        id="compare_jan_feb",
        label="Compare months",
        question="How did revenue change between January and February?",
        plan=QueryPlan(
            operation="compare_periods",
            metrics=["net_revenue"],
            comparison=Comparison(
                period_a=Period(
                    label="January 2026",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 31),
                ),
                period_b=Period(
                    label="February 2026",
                    start=date(2026, 2, 1),
                    end=date(2026, 2, 28),
                ),
            ),
        ),
    ),
    "revenue_by_category": Preset(
        id="revenue_by_category",
        label="Revenue by category",
        question="What is revenue by category?",
        plan=QueryPlan(
            operation="grouped_summary",
            metrics=["net_revenue"],
            group_by=["category"],
            sort_by=SortBy(field="net_revenue", direction="desc"),
            limit=10,
        ),
    ),
    "revenue_by_channel": Preset(
        id="revenue_by_channel",
        label="Sales-channel comparison",
        question="Compare revenue by sales channel.",
        plan=QueryPlan(
            operation="grouped_summary",
            metrics=["net_revenue"],
            group_by=["sales_channel"],
            sort_by=SortBy(field="net_revenue", direction="desc"),
            limit=10,
        ),
    ),
}


def get_examples() -> list[dict[str, str]]:
    return [
        {
            "preset_id": preset.id,
            "label": preset.label,
            "question": preset.question,
        }
        for preset in PRESETS.values()
    ]


def get_preset_plan(preset_id: str) -> QueryPlan | None:
    preset = PRESETS.get(preset_id)
    if preset is None:
        return None
    return preset.plan.model_copy(deep=True)


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def _clarification(question: str) -> QueryPlan:
    return QueryPlan(
        status="needs_clarification",
        clarification_question=question,
    )


def _unsupported(reason: str) -> QueryPlan:
    return QueryPlan(status="unsupported", unsupported_reason=reason)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _extract_metric(text: str) -> str:
    if "average order value" in text or re.search(r"\baov\b", text):
        return "average_order_value"
    if "gross" in text:
        return "gross_sales"
    if "discount" in text:
        return "total_discounts"
    if "units" in text or "quantity" in text:
        return "units_sold"
    if "transaction" in text or "order count" in text:
        return "transaction_count"
    return "net_revenue"


def _extract_dimensions(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for keyword, dimension in DIMENSION_KEYWORDS:
        match = re.search(rf"\b{re.escape(keyword)}\b", text)
        if match:
            found.append((match.start(), dimension))
    ordered = []
    for _, dimension in sorted(found):
        if dimension not in ordered:
            ordered.append(dimension)
    return ordered


def _extract_limit(text: str, default: int = 10) -> int:
    match = TOP_PATTERN.search(text)
    if match:
        return min(max(int(match.group(1)), 1), MAX_RESULT_LIMIT)
    if _contains_any(text, ("highest", "best", "lowest", "bottom")):
        return 1
    return min(default, MAX_RESULT_LIMIT)


def _extract_values(
    text: str, values: set[str]
) -> list[str]:
    found = []
    for value in values:
        if re.search(rf"\b{re.escape(value)}\b", text):
            if value == "canceled":
                value = "cancelled"
            if value not in found:
                found.append(value)
    return found


def _extract_filters(text: str, dimensions: list[str]) -> list[Filter]:
    filters: list[Filter] = []
    field_values = (
        ("region", REGION_VALUES),
        ("category", CATEGORY_VALUES),
        ("sales_channel", CHANNEL_VALUES),
        ("status", STATUS_VALUES),
    )
    for field, values in field_values:
        if field in dimensions:
            continue
        matched = _extract_values(text, values)
        if matched:
            filters.append(
                Filter(
                    field=field,
                    operator="in" if len(matched) > 1 else "eq",
                    values=matched,
                )
            )
    return filters


def _month_bounds(month_number: int, year: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month_number)[1]
    return date(year, month_number, 1), date(year, month_number, last_day)


def _month_name(month_number: int) -> str:
    return calendar.month_name[month_number]


def _extract_month_matches(text: str) -> list[tuple[int, int, int]]:
    matches = []
    for match in MONTH_PATTERN.finditer(text):
        month_number = MONTHS[match.group(1).lower()]
        year = int(match.group(2)) if match.group(2) else DEFAULT_DATASET_YEAR
        matches.append((match.start(), month_number, year))
    return matches


def mentions_month_without_year(question: str) -> bool:
    """Return True when the question names a month but no explicit year."""
    text = _normalize(question)
    return any(
        not match.group(2) for match in MONTH_PATTERN.finditer(text)
    )


def _extract_periods(text: str) -> list[Period]:
    periods = []
    for _, month_number, year in _extract_month_matches(text):
        start, end = _month_bounds(month_number, year)
        periods.append(
            Period(
                label=f"{_month_name(month_number)} {year}",
                start=start,
                end=end,
            )
        )
    return periods


def _extract_date_range(text: str) -> DateRange | None:
    months = _extract_month_matches(text)
    year_match = YEAR_PATTERN.search(text)
    if len(months) >= 2:
        first_start, _ = _month_bounds(months[0][1], months[0][2])
        _, last_end = _month_bounds(months[-1][1], months[-1][2])
        return DateRange(start=first_start, end=last_end)
    if len(months) == 1:
        start, end = _month_bounds(months[0][1], months[0][2])
        return DateRange(start=start, end=end)
    if year_match:
        year = int(year_match.group(1))
        return DateRange(start=date(year, 1, 1), end=date(year, 12, 31))
    return None


def _needs_region_clarification(text: str, dimensions: list[str]) -> bool:
    if "region" not in dimensions:
        return False
    if "within a region" in text or "in a region" in text:
        return not _extract_values(text, REGION_VALUES)
    return False


def interpret_rules(question: str) -> QueryPlan:
    text = _normalize(question)
    if not text:
        return _clarification("Please enter a sales question.")

    if RELATIVE_DATE_PATTERN.search(text):
        return _clarification(
            "Please specify the calendar month and year (for example, "
            "January 2026) so the period is unambiguous."
        )

    implausible_years = [
        int(match.group(1))
        for match in ANY_YEAR_PATTERN.finditer(text)
        if not (MIN_DATA_YEAR <= int(match.group(1)) <= MAX_DATA_YEAR)
    ]
    # Also catch short "year" mentions like "year 999" or "in 850".
    short_year = re.search(r"\b(?:year|in)\s+(\d{1,3})\b", text)
    if short_year:
        implausible_years.append(int(short_year.group(1)))
    if implausible_years:
        year = implausible_years[0]
        return _clarification(
            f"I couldn't use the year {year} — it looks outside the range of "
            "the available data. Did you mean a year between 1900 and 2099? "
            "The dataset currently covers 2026."
        )

    for term, reason in UNSUPPORTED_TERMS.items():
        if term in text:
            return _unsupported(reason)

    dimensions = _extract_dimensions(text)
    if _needs_region_clarification(text, dimensions):
        return _clarification(
            "Which region do you mean: East, North, South, or West?"
        )

    periods = _extract_periods(text)
    compare_requested = _contains_any(
        text,
        (
            "change between",
            "compare",
            "comparison",
            "difference between",
            "versus",
            " vs ",
            "growth",
            "month over month",
            "month-on-month",
        ),
    )

    if compare_requested:
        if len(periods) >= 2:
            metric = _extract_metric(text)
            return QueryPlan(
                operation="compare_periods",
                metrics=[metric],
                filters=_extract_filters(text, dimensions),
                comparison=Comparison(
                    period_a=periods[0],
                    period_b=periods[1],
                ),
            )
        if dimensions:
            metric = _extract_metric(text)
            return QueryPlan(
                operation="grouped_summary",
                metrics=[metric],
                group_by=dimensions,
                filters=_extract_filters(text, dimensions),
                sort_by=SortBy(field=metric, direction="desc"),
                limit=_extract_limit(text),
            )
        return _clarification(
            "Which two months should I compare? Please name both months, "
            "for example January 2026 and February 2026."
        )

    if "trend" in text or "over time" in text:
        return QueryPlan(
            operation="time_series",
            metrics=[_extract_metric(text)],
            date_range=_extract_date_range(text),
            limit=MAX_RESULT_LIMIT,
        )

    metric = _extract_metric(text)
    filters = _extract_filters(text, dimensions)

    if dimensions:
        if dimensions == ["order_month"]:
            return QueryPlan(
                operation="time_series",
                metrics=[metric],
                date_range=_extract_date_range(text),
                limit=MAX_RESULT_LIMIT,
            )
        return QueryPlan(
            operation="grouped_summary",
            metrics=[metric],
            group_by=dimensions,
            filters=filters,
            date_range=_extract_date_range(text),
            sort_by=SortBy(field=metric, direction="desc"),
            limit=_extract_limit(text),
        )

    if _contains_any(
        text,
        (
            "total",
            "overall",
            "sum of",
            "what is the revenue",
            "what's the revenue",
            "how much revenue",
            "how much sales",
            "revenue",
            "sales",
            "transactions",
            "units sold",
            "average order value",
            "discounts",
            "gross",
        ),
    ):
        return QueryPlan(
            operation="total",
            metrics=[metric],
            filters=filters,
            date_range=_extract_date_range(text),
        )

    if _contains_any(
        text,
        ("highest", "top", "best", "rank", "which", "show me"),
    ):
        return _clarification(
            "Which dimension should I use: product, category, region, sales "
            "channel, month, or status?"
        )

    return _clarification(
        "I can answer totals, rankings by product/category/region/channel, "
        "monthly trends, and two-month comparisons. Please rephrase the "
        "question with one of those analyses."
    )
