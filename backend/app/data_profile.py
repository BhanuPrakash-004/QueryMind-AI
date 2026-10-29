"""Generate DATA_PROFILE.md from the actual sales CSV.

Run from the backend directory:
    python -m app.data_profile ../data/sales.csv --output ../DATA_PROFILE.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .business_rules import (
    PRIMARY_REVENUE_LABEL,
    SOURCE_HEADERS,
    ParsedRow,
    RejectedRow,
    dataset_totals,
    normalize_text,
    parse_order_date,
    parse_quantity,
    parse_row,
    validate_headers,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "data" / "sales.csv"
DEFAULT_OUTPUT = REPO_ROOT / "DATA_PROFILE.md"

_TEXT_COLUMNS = (
    "Transaction_Id",
    "Product",
    "Category",
    "Region",
    "Sales_channel",
    "Status",
)


@dataclass
class Profile:
    source: Path
    headers: list[str]
    missing_headers: list[str]
    extra_headers: list[str]
    rows_read: int
    missing_values: Counter[str]
    accepted: list[ParsedRow]
    rejected: list[RejectedRow]
    duplicate_ids: list[str]
    status_raw: Counter[str]
    status_normalized: Counter[str]
    regions: list[str]
    categories: list[str]
    sales_channels: list[str]
    products: list[str]
    raw_date_min: date | None
    raw_date_max: date | None
    valid_date_min: date | None
    valid_date_max: date | None
    zero_quantity_ids: list[str]
    whitespace_fields_normalized: int
    discount_rows: list[tuple[str, Decimal]]
    totals: dict[str, Decimal | int | None] = field(default_factory=dict)


def build_profile(csv_path: Path) -> Profile:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")

        headers = [header.strip() for header in reader.fieldnames if header]
        missing_headers, extra_headers = validate_headers(headers)

        rows: list[tuple[int, dict[str, str]]] = []
        for row_number, raw in enumerate(reader, start=2):
            cleaned: dict[str, str] = {}
            for key, value in raw.items():
                if key is None:
                    continue
                cleaned[key.strip()] = value if value is not None else ""
            rows.append((row_number, cleaned))

    missing_values: Counter[str] = Counter({header: 0 for header in SOURCE_HEADERS})
    status_raw: Counter[str] = Counter()
    zero_quantity_ids: list[str] = []
    whitespace_fields_normalized = 0
    raw_dates: list[date] = []
    seen_ids: dict[str, int] = {}
    duplicate_ids: list[str] = []

    for row_number, raw in rows:
        for header in SOURCE_HEADERS:
            if not normalize_text(raw.get(header)):
                missing_values[header] += 1

        status_raw[normalize_text(raw.get("Status"))] += 1

        transaction_id = normalize_text(raw.get("Transaction_Id"))
        if transaction_id:
            if transaction_id in seen_ids:
                duplicate_ids.append(transaction_id)
            else:
                seen_ids[transaction_id] = row_number

        for column in _TEXT_COLUMNS:
            original = raw.get(column, "")
            if original and original != normalize_text(original):
                whitespace_fields_normalized += 1

        try:
            quantity = parse_quantity(raw.get("Quantity"))
            if quantity == 0 and transaction_id:
                zero_quantity_ids.append(transaction_id)
        except ValueError:
            pass

        try:
            raw_dates.append(parse_order_date(raw.get("Order_date")))
        except ValueError:
            pass

    accepted: list[ParsedRow] = []
    rejected: list[RejectedRow] = []
    first_seen: dict[str, int] = {}

    for row_number, raw in rows:
        transaction_id = normalize_text(raw.get("Transaction_Id"))
        if transaction_id and transaction_id in first_seen:
            rejected.append(
                RejectedRow(
                    row_number=row_number,
                    transaction_id=transaction_id,
                    reason=(
                        "duplicate transaction_id in file "
                        f"(first at row {first_seen[transaction_id]})"
                    ),
                    raw=raw,
                )
            )
            continue
        if transaction_id:
            first_seen[transaction_id] = row_number

        try:
            accepted.append(parse_row(raw, row_number))
        except ValueError as exc:
            rejected.append(
                RejectedRow(
                    row_number=row_number,
                    transaction_id=transaction_id,
                    reason=str(exc),
                    raw=raw,
                )
            )

    status_normalized: Counter[str] = Counter()
    for row in accepted:
        status_normalized[row.status] += 1

    regions = sorted({row.region for row in accepted})
    categories = sorted({row.category for row in accepted})
    sales_channels = sorted({row.sales_channel for row in accepted})
    products = sorted({row.product for row in accepted})

    valid_dates = [row.order_date for row in accepted]
    discount_rows = [
        (row.transaction_id, row.discount_amount)
        for row in accepted
        if row.discount_amount > 0
    ]

    return Profile(
        source=csv_path,
        headers=headers,
        missing_headers=missing_headers,
        extra_headers=extra_headers,
        rows_read=len(rows),
        missing_values=missing_values,
        accepted=accepted,
        rejected=rejected,
        duplicate_ids=duplicate_ids,
        status_raw=status_raw,
        status_normalized=status_normalized,
        regions=regions,
        categories=categories,
        sales_channels=sales_channels,
        products=products,
        raw_date_min=min(raw_dates) if raw_dates else None,
        raw_date_max=max(raw_dates) if raw_dates else None,
        valid_date_min=min(valid_dates) if valid_dates else None,
        valid_date_max=max(valid_dates) if valid_dates else None,
        zero_quantity_ids=zero_quantity_ids,
        whitespace_fields_normalized=whitespace_fields_normalized,
        discount_rows=discount_rows,
        totals=dataset_totals(accepted),
    )


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _money(value: Decimal | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return f"{value:,}"


def _date_range(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return "No valid dates"
    return f"{start.isoformat()} to {end.isoformat()}"


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def render_profile(profile: Profile) -> str:
    totals = profile.totals
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        "# Data Profile — QueryMind-AI",
        "",
        f"Source: `{_relative(profile.source)}`  ",
        f"Generated: {generated_at}  ",
        "Generated by `python -m app.data_profile` from the actual CSV. "
        "No values in this document are invented.",
        "",
        "## Summary",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Data rows | {profile.rows_read:,} |",
        f"| Columns | {len(profile.headers)} |",
        f"| Importable rows | {len(profile.accepted):,} |",
        f"| Rejected rows | {len(profile.rejected):,} |",
        f"| Duplicate transaction IDs | {len(profile.duplicate_ids):,} |",
        f"| Date coverage (all parseable rows) | "
        f"{_date_range(profile.raw_date_min, profile.raw_date_max)} |",
        f"| Date coverage (importable rows) | "
        f"{_date_range(profile.valid_date_min, profile.valid_date_max)} |",
        "| Currency | Not specified in the dataset |",
        "",
        "## Columns and missing values",
        "",
        "| Column | Missing values |",
        "|---|---:|",
    ]

    for header in SOURCE_HEADERS:
        lines.append(f"| `{header}` | {profile.missing_values[header]:,} |")

    if profile.missing_headers:
        lines.extend(
            [
                "",
                "Missing required headers: "
                + ", ".join(f"`{item}`" for item in profile.missing_headers),
            ]
        )
    if profile.extra_headers:
        lines.extend(
            [
                "",
                "Extra headers ignored by the importer: "
                + ", ".join(f"`{item}`" for item in profile.extra_headers),
            ]
        )

    lines.extend(
        [
            "",
            "## Distinct values (importable rows)",
            "",
            "| Field | Values |",
            "|---|---|",
            f"| Status (raw, all rows) | "
            + ", ".join(
                f"{_md(name or '(empty)')} ({count})"
                for name, count in sorted(profile.status_raw.items())
            )
            + " |",
            f"| Status (normalized, importable) | "
            + ", ".join(
                f"{_md(name)} ({count})"
                for name, count in sorted(profile.status_normalized.items())
            )
            + " |",
            f"| Regions ({len(profile.regions)}) | "
            + ", ".join(_md(item) for item in profile.regions)
            + " |",
            f"| Categories ({len(profile.categories)}) | "
            + ", ".join(_md(item) for item in profile.categories)
            + " |",
            f"| Sales channels ({len(profile.sales_channels)}) | "
            + ", ".join(_md(item) for item in profile.sales_channels)
            + " |",
            f"| Products ({len(profile.products)}) | "
            + ", ".join(_md(item) for item in profile.products)
            + " |",
            "",
            "## Data-quality findings",
            "",
            f"- Missing values: "
            + (
                ", ".join(
                    f"`{column}`={count}"
                    for column, count in profile.missing_values.items()
                    if count
                )
                or "none"
            ),
            f"- Duplicate transaction IDs: "
            + (", ".join(profile.duplicate_ids) if profile.duplicate_ids else "none"),
            f"- Zero-quantity records: "
            + (
                ", ".join(profile.zero_quantity_ids)
                if profile.zero_quantity_ids
                else "none"
            ),
            f"- Rows with discounts: {len(profile.discount_rows):,}",
            f"- Fields normalized for whitespace: "
            f"{profile.whitespace_fields_normalized:,}",
            f"- Rejected rows: {len(profile.rejected):,} "
            "(see table below; rejected rows are not imported)",
            "",
            "## Revenue profile (importable rows)",
            "",
            f"Primary metric: **{PRIMARY_REVENUE_LABEL}** "
            "(completed transactions, net of transaction-level discounts).",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Completed gross sales | {_money(totals.get('completed_gross_sales'))} |",
            f"| Completed discounts | {_money(totals.get('completed_discounts'))} |",
            f"| Completed net revenue | {_money(totals.get('completed_net_revenue'))} |",
            f"| Completed transactions | {_money(totals.get('completed_transaction_count'))} |",
            f"| Units sold (completed) | {_money(totals.get('units_sold'))} |",
            f"| Average order value | {_money(totals.get('average_order_value'))} |",
            f"| Excluded gross sales (non-completed) | "
            f"{_money(totals.get('excluded_gross_sales'))} |",
            f"| Excluded net revenue (non-completed) | "
            f"{_money(totals.get('excluded_net_revenue'))} |",
            f"| Excluded transactions (non-completed) | "
            f"{_money(totals.get('excluded_transaction_count'))} |",
            "",
            "Reconciliation: completed gross sales − completed discounts = "
            "completed net revenue.",
            "",
            "## Rejected rows",
            "",
        ]
    )

    if profile.rejected:
        lines.extend(
            [
                "| CSV row | Transaction ID | Reason |",
                "|---:|---|---|",
            ]
        )
        for row in profile.rejected:
            lines.append(
                f"| {row.row_number} | {_md(row.transaction_id or '(empty)')} | "
                f"{_md(row.reason)} |"
            )
    else:
        lines.append("None.")

    lines.extend(
        [
            "",
            "## Assumptions and policies",
            "",
            "- Dates are parsed explicitly as `DD-MM-YYYY`, the format used by the "
            "supplied file.",
            "- `Discount_amount` is treated as a transaction-level discount amount, "
            "not a per-unit discount; the file contains one row per transaction ID, "
            "so the distinction cannot be independently confirmed from the data.",
            "- The primary revenue metric is completed net revenue: "
            "`(quantity × unit_price) − discount_amount` for transactions whose "
            "normalized status is `completed`.",
            "- Non-completed statuses are retained in the database but excluded "
            "from completed metrics.",
            "- A missing `Unit_price` rejects the row because revenue cannot be "
            "calculated safely; rejected rows are reported, not silently dropped.",
            "- A missing `Discount_amount` defaults to 0 with a warning.",
            "- A discount greater than the transaction's gross sales is rejected "
            "as invalid because it would produce negative net revenue.",
            "- Zero-quantity rows are retained and flagged as suspicious.",
            "- Duplicate transaction IDs keep the first valid occurrence and reject "
            "later duplicates.",
            "- Status values are trimmed, whitespace-collapsed, and lowercased; "
            "unknown statuses are retained as-is.",
            "- The dataset does not specify a currency, so no currency symbol is "
            "assumed.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "cd backend",
            "python -m app.data_profile ../data/sales.csv --output ../DATA_PROFILE.md",
            "```",
            "",
        ]
    )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate DATA_PROFILE.md from the actual sales CSV."
    )
    parser.add_argument(
        "csv_path", nargs="?", type=Path, default=DEFAULT_CSV
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT
    )
    args = parser.parse_args(argv)

    csv_path = args.csv_path.resolve()
    output_path = args.output.resolve()

    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 2

    try:
        profile = build_profile(csv_path)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Could not profile CSV: {exc}", file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_profile(profile), encoding="utf-8")

    print(f"Wrote {output_path}")
    print(
        f"Rows read: {profile.rows_read}; "
        f"importable: {len(profile.accepted)}; "
        f"rejected: {len(profile.rejected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
