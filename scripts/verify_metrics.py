"""Independent CSV/Decimal verification of the SQL analytics engine.

Run from the repository root:
    backend\\.venv\\Scripts\\python.exe scripts\\verify_metrics.py

This script parses the source CSV with the canonical Python rules, computes
expected metrics without SQL, then compares them with the runtime database
through the same public analytics functions used by the API.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.analytics import (  # noqa: E402
    compare_monthly_revenue,
    get_dataset_summary,
    get_monthly_revenue_trend,
    get_sales_by_region,
    get_top_product_by_revenue,
    get_total_revenue,
)
from app.business_rules import (  # noqa: E402
    COMPLETED_STATUS,
    MONEY_QUANT,
    dataset_totals,
    net_revenue,
)
from app.database import runtime_session  # noqa: E402
from app.import_csv import parse_rows, read_csv  # noqa: E402
from app.query_planner import Period  # noqa: E402

CSV_PATH = REPO_ROOT / "data" / "sales.csv"


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANT)


def check(label: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"PASS  {label}: {actual}")


def expected_groups(rows, field: str) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in rows:
        if row.status == COMPLETED_STATUS:
            totals[getattr(row, field)] += net_revenue(
                row.quantity, row.unit_price, row.discount_amount
            )
    return dict(totals)


def expected_monthly(rows) -> list[tuple[str, Decimal]]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in rows:
        if row.status == COMPLETED_STATUS:
            key = row.order_date.strftime("%Y-%m-01")
            totals[key] += net_revenue(
                row.quantity, row.unit_price, row.discount_amount
            )
    return sorted(totals.items())


def expected_period_revenue(rows, start, end) -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        if (
            row.status == COMPLETED_STATUS
            and start <= row.order_date <= end
        ):
            total += net_revenue(
                row.quantity, row.unit_price, row.discount_amount
            )
    return total.quantize(MONEY_QUANT)


def main() -> int:
    if not CSV_PATH.exists():
        print(f"CSV not found: {CSV_PATH}", file=sys.stderr)
        return 2

    _, _, raw_rows = read_csv(CSV_PATH)
    parsed, rejected, _ = parse_rows(raw_rows)
    expected = dataset_totals(parsed)
    completed_rows = [row for row in parsed if row.status == COMPLETED_STATUS]

    print(f"CSV: {CSV_PATH}")
    print(f"Parsed rows: {len(parsed)}; rejected: {len(rejected)}")

    with runtime_session() as session:
        total = get_total_revenue(session)
        db_metrics = total["metrics"]

        check(
            "completed gross sales",
            money(db_metrics["gross_sales"]),
            money(expected["completed_gross_sales"]),
        )
        check(
            "completed discounts",
            money(db_metrics["total_discounts"]),
            money(expected["completed_discounts"]),
        )
        check(
            "completed net revenue",
            money(db_metrics["net_revenue"]),
            money(expected["completed_net_revenue"]),
        )
        check(
            "completed transaction count",
            db_metrics["transaction_count"],
            expected["completed_transaction_count"],
        )
        check(
            "units sold",
            db_metrics["units_sold"],
            expected["units_sold"],
        )
        check(
            "average order value",
            money(db_metrics["average_order_value"]),
            money(expected["average_order_value"]),
        )
        check(
            "net revenue = gross sales - discounts",
            money(db_metrics["net_revenue"]),
            money(db_metrics["gross_sales"] - db_metrics["total_discounts"]),
        )

        reconciliation = total["reconciliation"]
        check(
            "excluded returned net revenue",
            money(reconciliation["excluded_net_revenue"]),
            money(expected["excluded_net_revenue"]),
        )
        check(
            "excluded transaction count",
            reconciliation["excluded_transaction_count"],
            expected["excluded_transaction_count"],
        )

        product_totals = expected_groups(completed_rows, "product")
        expected_top_product, expected_top_value = max(
            product_totals.items(), key=lambda item: (item[1], item[0])
        )
        top = get_top_product_by_revenue(session)["supporting_data"][0]
        check("top product", top["product"], expected_top_product)
        check(
            "top product net revenue",
            money(top["net_revenue"]),
            money(expected_top_value),
        )

        expected_trend = [
            (month, money(value)) for month, value in expected_monthly(parsed)
        ]
        actual_trend = [
            (row["order_month"], money(row["net_revenue"]))
            for row in get_monthly_revenue_trend(session)["supporting_data"]
        ]
        check("monthly trend ordering", actual_trend, expected_trend)

        region_totals = expected_groups(completed_rows, "region")
        expected_regions = sorted(
            region_totals.items(), key=lambda item: (-item[1], item[0])
        )
        actual_regions = [
            (row["region"], money(row["net_revenue"]))
            for row in get_sales_by_region(session)["supporting_data"]
        ]
        check("region ranking", actual_regions, expected_regions)

        jan = Period(label="January", start="2026-01-01", end="2026-01-31")
        feb = Period(label="February", start="2026-02-01", end="2026-02-28")
        comparison = compare_monthly_revenue(session, jan, feb)
        expected_jan = expected_period_revenue(
            parsed, jan.start, jan.end
        )
        expected_feb = expected_period_revenue(
            parsed, feb.start, feb.end
        )
        check(
            "January net revenue",
            money(comparison["periods"][0]["metrics"]["net_revenue"]),
            expected_jan,
        )
        check(
            "February net revenue",
            money(comparison["periods"][1]["metrics"]["net_revenue"]),
            expected_feb,
        )
        expected_change = money(expected_feb - expected_jan)
        check(
            "month-over-month absolute change",
            money(comparison["changes"][0]["absolute_change"]),
            expected_change,
        )
        expected_percentage = (
            (expected_feb - expected_jan) / expected_jan * Decimal("100")
        ).quantize(Decimal("0.01"))
        check(
            "month-over-month percentage change",
            comparison["changes"][0]["percentage_change"],
            expected_percentage,
        )

        summary = get_dataset_summary(session)
        check("database row count", summary["row_count"], len(parsed))
        check(
            "date coverage start",
            summary["date_coverage"]["start"],
            min(row.order_date for row in parsed).isoformat(),
        )
        check(
            "date coverage end",
            summary["date_coverage"]["end"],
            max(row.order_date for row in parsed).isoformat(),
        )

    print("\nAll independent metric checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
