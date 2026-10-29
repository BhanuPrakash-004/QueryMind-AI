"""Canonical business definitions, CSV validation, and metric formulas.

Every revenue number in the application must derive from the definitions in
this module. The SQL engine mirrors these formulas, and the independent
verification script uses the pure-Python helpers here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

SOURCE_HEADERS: tuple[str, ...] = (
    "Transaction_Id",
    "Order_date",
    "Product",
    "Category",
    "Region",
    "Sales_channel",
    "Quantity",
    "Unit_price",
    "Discount_amount",
    "Status",
)

DATE_FORMAT = "%d-%m-%Y"
MONEY_QUANT = Decimal("0.01")
COMPLETED_STATUS = "completed"

# The primary total-revenue metric is completed net revenue. Non-completed
# statuses are retained in the database but excluded from completed metrics.
PRIMARY_REVENUE_METRIC = "completed_net_revenue"
PRIMARY_REVENUE_LABEL = "Completed net revenue"

METRIC_LABELS: dict[str, str] = {
    "net_revenue": "net revenue",
    "gross_sales": "gross sales",
    "total_discounts": "discounts",
    "transaction_count": "transaction count",
    "units_sold": "units sold",
    "average_order_value": "average order value",
}

DIMENSION_LABELS: dict[str, str] = {
    "product": "product",
    "category": "category",
    "region": "region",
    "sales_channel": "sales channel",
    "order_month": "month",
    "status": "status",
}

METRIC_DEFINITIONS: dict[str, str] = {
    "net_revenue": (
        "Net revenue = Σ(quantity × unit_price − discount_amount) over {scope}."
    ),
    "gross_sales": "Gross sales = Σ(quantity × unit_price) over {scope}.",
    "total_discounts": "Discounts = Σ(discount_amount) over {scope}.",
    "transaction_count": (
        "Transaction count = count of distinct transaction_id values over {scope}."
    ),
    "units_sold": "Units sold = Σ(quantity) over {scope}.",
    "average_order_value": (
        "Average order value = net revenue ÷ transaction count over {scope}."
    ),
}


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


def dimension_label(dimension: str) -> str:
    return DIMENSION_LABELS.get(dimension, dimension.replace("_", " "))


def metric_definition(metric: str, scope: str = "completed transactions") -> str:
    template = METRIC_DEFINITIONS.get(
        metric, "Metric {metric} over {scope}."
    )
    return template.format(metric=metric_label(metric), scope=scope)


STATUS_ALIASES: dict[str, str] = {
    "completed": "completed",
    "complete": "completed",
    "returned": "returned",
    "return": "returned",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "pending": "pending",
}

_QUANTITY_PATTERN = re.compile(r"\d+")


@dataclass(frozen=True)
class RejectedRow:
    row_number: int
    transaction_id: str
    reason: str
    raw: dict[str, str]


@dataclass
class ParsedRow:
    row_number: int
    transaction_id: str
    order_date: date
    product: str
    category: str
    region: str
    sales_channel: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    status: str
    warnings: list[str] = field(default_factory=list)


def normalize_text(value: str | None) -> str:
    """Trim and collapse internal whitespace."""
    return " ".join((value or "").split())


def normalize_status(value: str | None) -> str:
    cleaned = normalize_text(value).lower()
    if not cleaned:
        raise ValueError("missing status")
    return STATUS_ALIASES.get(cleaned, cleaned)


def parse_order_date(value: str | None) -> date:
    cleaned = normalize_text(value)
    if not cleaned:
        raise ValueError("missing order_date")
    try:
        return datetime.strptime(cleaned, DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(
            f"invalid order_date '{cleaned}' (expected DD-MM-YYYY)"
        ) from exc


def parse_decimal(value: str | None, field_name: str) -> Decimal:
    cleaned = normalize_text(value)
    if not cleaned:
        raise ValueError(f"missing {field_name}")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field_name} '{cleaned}'") from exc
    if not amount.is_finite():
        raise ValueError(f"invalid {field_name} '{cleaned}'")
    return amount


def parse_quantity(value: str | None) -> int:
    cleaned = normalize_text(value)
    if not cleaned:
        raise ValueError("missing quantity")
    if not _QUANTITY_PATTERN.fullmatch(cleaned):
        raise ValueError(f"invalid quantity '{cleaned}'")
    return int(cleaned)


def validate_headers(headers: Sequence[str]) -> tuple[list[str], list[str]]:
    normalized = [header.strip() for header in headers if header is not None]
    missing = [header for header in SOURCE_HEADERS if header not in normalized]
    extra = [
        header for header in normalized if header and header not in SOURCE_HEADERS
    ]
    return missing, extra


def parse_row(raw: Mapping[str, str], row_number: int) -> ParsedRow:
    """Validate and normalize one CSV row.

    Raises:
        ValueError: when the row cannot be imported safely.
    """

    def value(column: str) -> str:
        return raw.get(column, "")

    transaction_id = normalize_text(value("Transaction_Id"))
    if not transaction_id:
        raise ValueError("missing transaction_id")

    product = normalize_text(value("Product"))
    if not product:
        raise ValueError("missing product")

    category = normalize_text(value("Category"))
    if not category:
        raise ValueError("missing category")

    region = normalize_text(value("Region"))
    if not region:
        raise ValueError("missing region")

    sales_channel = normalize_text(value("Sales_channel"))
    if not sales_channel:
        raise ValueError("missing sales_channel")

    order_date = parse_order_date(value("Order_date"))
    quantity = parse_quantity(value("Quantity"))

    unit_price = parse_decimal(value("Unit_price"), "unit_price")
    if unit_price < 0:
        raise ValueError("unit_price must not be negative")

    warnings: list[str] = []
    discount_raw = normalize_text(value("Discount_amount"))
    if discount_raw:
        discount_amount = parse_decimal(discount_raw, "discount_amount")
    else:
        discount_amount = Decimal("0.00")
        warnings.append("missing discount_amount; defaulted to 0")

    if discount_amount < 0:
        raise ValueError("discount_amount must not be negative")

    gross = gross_sales(quantity, unit_price)
    if discount_amount > gross:
        raise ValueError(
            f"discount_amount {discount_amount} exceeds gross sales {gross}"
        )

    if quantity == 0:
        warnings.append("zero quantity retained")

    status = normalize_status(value("Status"))
    if status != COMPLETED_STATUS:
        warnings.append(f"status '{status}' excluded from completed revenue")

    return ParsedRow(
        row_number=row_number,
        transaction_id=transaction_id,
        order_date=order_date,
        product=product,
        category=category,
        region=region,
        sales_channel=sales_channel,
        quantity=quantity,
        unit_price=unit_price,
        discount_amount=discount_amount,
        status=status,
        warnings=warnings,
    )


def gross_sales(quantity: int, unit_price: Decimal) -> Decimal:
    return (Decimal(quantity) * unit_price).quantize(
        MONEY_QUANT, rounding=ROUND_HALF_UP
    )


def net_revenue(
    quantity: int, unit_price: Decimal, discount_amount: Decimal
) -> Decimal:
    return (gross_sales(quantity, unit_price) - discount_amount).quantize(
        MONEY_QUANT, rounding=ROUND_HALF_UP
    )


def dataset_totals(rows: Iterable[ParsedRow]) -> dict[str, Decimal | int | None]:
    """Compute canonical totals using the documented revenue definitions."""
    row_list = list(rows)
    completed = [row for row in row_list if row.status == COMPLETED_STATUS]
    excluded = [row for row in row_list if row.status != COMPLETED_STATUS]

    completed_gross = sum(
        (gross_sales(row.quantity, row.unit_price) for row in completed),
        Decimal("0.00"),
    )
    completed_discounts = sum(
        (row.discount_amount for row in completed), Decimal("0.00")
    )
    completed_net = sum(
        (
            net_revenue(row.quantity, row.unit_price, row.discount_amount)
            for row in completed
        ),
        Decimal("0.00"),
    )
    completed_count = len({row.transaction_id for row in completed})
    units_sold = sum(row.quantity for row in completed)

    average_order_value = (
        (completed_net / completed_count).quantize(
            MONEY_QUANT, rounding=ROUND_HALF_UP
        )
        if completed_count
        else None
    )

    excluded_gross = sum(
        (gross_sales(row.quantity, row.unit_price) for row in excluded),
        Decimal("0.00"),
    )
    excluded_net = sum(
        (
            net_revenue(row.quantity, row.unit_price, row.discount_amount)
            for row in excluded
        ),
        Decimal("0.00"),
    )
    excluded_count = len({row.transaction_id for row in excluded})

    return {
        "completed_gross_sales": completed_gross,
        "completed_discounts": completed_discounts,
        "completed_net_revenue": completed_net,
        "completed_transaction_count": completed_count,
        "units_sold": units_sold,
        "average_order_value": average_order_value,
        "excluded_gross_sales": excluded_gross,
        "excluded_net_revenue": excluded_net,
        "excluded_transaction_count": excluded_count,
    }
