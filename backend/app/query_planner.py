"""Validated analytics query-plan schema.

The language model may propose a plan, but only this schema and the application
rules decide whether it can reach the analytics engine. The model never writes
SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterpretationStatus = Literal["ready", "needs_clarification", "unsupported"]
Operation = Literal["total", "grouped_summary", "time_series", "compare_periods"]
MetricName = Literal[
    "net_revenue",
    "gross_sales",
    "total_discounts",
    "transaction_count",
    "units_sold",
    "average_order_value",
]
DimensionName = Literal[
    "product",
    "category",
    "region",
    "sales_channel",
    "order_month",
    "status",
]
FilterField = Literal["product", "category", "region", "sales_channel", "status"]
FilterOperator = Literal["eq", "in"]
SortField = Literal[
    "net_revenue",
    "gross_sales",
    "total_discounts",
    "transaction_count",
    "units_sold",
    "average_order_value",
    "product",
    "category",
    "region",
    "sales_channel",
    "order_month",
    "status",
]
SortDirection = Literal["asc", "desc"]
ChangeType = Literal["absolute", "percentage"]

MAX_RESULT_LIMIT = 25
MAX_QUESTION_LENGTH = 500

OPERATIONS: tuple[str, ...] = (
    "total",
    "grouped_summary",
    "time_series",
    "compare_periods",
)
METRICS: tuple[str, ...] = (
    "net_revenue",
    "gross_sales",
    "total_discounts",
    "transaction_count",
    "units_sold",
    "average_order_value",
)
DIMENSIONS: tuple[str, ...] = (
    "product",
    "category",
    "region",
    "sales_channel",
    "order_month",
    "status",
)
FILTER_FIELDS: tuple[str, ...] = (
    "product",
    "category",
    "region",
    "sales_channel",
    "status",
)


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def check_order(self) -> "DateRange":
        if self.start and self.end and self.start > self.end:
            raise ValueError("date_range.start must be on or before date_range.end")
        return self


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field: FilterField
    operator: FilterOperator = "eq"
    values: list[str] = Field(min_length=1, max_length=20)

    @field_validator("values")
    @classmethod
    def clean_values(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("filter values must not be empty")
        return cleaned

    @model_validator(mode="after")
    def check_operator(self) -> "Filter":
        if self.operator == "eq" and len(self.values) != 1:
            raise ValueError("eq filters require exactly one value")
        return self


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=80)
    start: date
    end: date

    @model_validator(mode="after")
    def check_order(self) -> "Period":
        if self.start > self.end:
            raise ValueError("period.start must be on or before period.end")
        return self


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_a: Period
    period_b: Period
    change_types: list[ChangeType] = Field(
        default_factory=lambda: ["absolute", "percentage"], min_length=1
    )

    @field_validator("change_types")
    @classmethod
    def unique_change_types(cls, values: list[ChangeType]) -> list[ChangeType]:
        if len(set(values)) != len(values):
            raise ValueError("change_types must be unique")
        return values


class SortBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: SortField
    direction: SortDirection = "desc"


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: InterpretationStatus = "ready"
    operation: Operation | None = None
    metrics: list[MetricName] = Field(
        default_factory=lambda: ["net_revenue"]
    )
    group_by: list[DimensionName] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    date_range: DateRange | None = None
    comparison: Comparison | None = None
    sort_by: SortBy | None = None
    limit: int = Field(default=10, ge=1, le=MAX_RESULT_LIMIT)
    clarification_question: str | None = None
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> "QueryPlan":
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must be unique")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by dimensions must be unique")

        if self.status != "ready":
            if self.status == "needs_clarification":
                if not (self.clarification_question or "").strip():
                    raise ValueError(
                        "clarification_question is required when status is "
                        "needs_clarification"
                    )
            if self.status == "unsupported":
                if not (self.unsupported_reason or "").strip():
                    raise ValueError(
                        "unsupported_reason is required when status is unsupported"
                    )
            return self

        if self.operation is None:
            raise ValueError("operation is required when status is ready")
        if not self.metrics:
            raise ValueError("at least one metric is required when status is ready")
        if self.clarification_question or self.unsupported_reason:
            raise ValueError(
                "ready plans must not include clarification or unsupported text"
            )

        if self.operation == "total":
            if self.group_by:
                raise ValueError("total does not support group_by")
            if self.comparison:
                raise ValueError("total does not support comparison")
        elif self.operation == "grouped_summary":
            if not self.group_by:
                raise ValueError("grouped_summary requires at least one group_by")
            if self.comparison:
                raise ValueError("grouped_summary does not support comparison")
        elif self.operation == "time_series":
            if self.group_by:
                raise ValueError(
                    "time_series groups by month automatically; group_by must be empty"
                )
            if self.comparison:
                raise ValueError("time_series does not support comparison")
        elif self.operation == "compare_periods":
            if self.comparison is None:
                raise ValueError("compare_periods requires comparison periods")
            if self.group_by:
                raise ValueError("compare_periods does not support group_by")
            if self.date_range is not None:
                raise ValueError(
                    "compare_periods uses comparison periods, not date_range"
                )

        if self.sort_by is not None:
            allowed_sort_fields = set(self.metrics) | set(self.group_by) | {
                "order_month"
            }
            if self.sort_by.field not in allowed_sort_fields:
                raise ValueError(
                    "sort_by.field must be a selected metric or grouping dimension"
                )

        return self


def plan_is_executable(plan: QueryPlan) -> bool:
    return plan.status == "ready" and plan.operation is not None
