"""Deterministic CSV importer with data-quality reporting.

Run from the backend directory:
    python -m app.import_csv ../data/sales.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, insert, select

from .business_rules import (
    ParsedRow,
    RejectedRow,
    normalize_text,
    parse_row,
    validate_headers,
)
from .database import get_admin_engine
from .models import SalesTransaction

BATCH_SIZE = 500


def read_csv(path: Path) -> tuple[list[str], list[str], list[tuple[int, dict[str, str]]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")

        headers = [header.strip() for header in reader.fieldnames if header]
        missing, extra = validate_headers(headers)
        if missing:
            raise ValueError(
                "missing required columns: " + ", ".join(missing)
            )

        rows: list[tuple[int, dict[str, str]]] = []
        for row_number, raw in enumerate(reader, start=2):
            cleaned: dict[str, str] = {}
            for key, value in raw.items():
                if key is None:
                    continue
                cleaned[key.strip()] = value if value is not None else ""
            rows.append((row_number, cleaned))

    return headers, extra, rows


def parse_rows(
    rows: list[tuple[int, dict[str, str]]],
) -> tuple[list[ParsedRow], list[RejectedRow], list[str]]:
    parsed: list[ParsedRow] = []
    rejected: list[RejectedRow] = []
    warnings: list[str] = []
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
            row = parse_row(raw, row_number)
        except ValueError as exc:
            rejected.append(
                RejectedRow(
                    row_number=row_number,
                    transaction_id=transaction_id,
                    reason=str(exc),
                    raw=raw,
                )
            )
            continue

        parsed.append(row)
        for warning in row.warnings:
            warnings.append(
                f"row {row_number} ({row.transaction_id}): {warning}"
            )

    return parsed, rejected, warnings


def _chunked(items: list[Any], size: int) -> Iterator[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def row_payload(row: ParsedRow) -> dict[str, Any]:
    return {
        "transaction_id": row.transaction_id,
        "order_date": row.order_date,
        "product": row.product,
        "category": row.category,
        "region": row.region,
        "sales_channel": row.sales_channel,
        "quantity": row.quantity,
        "unit_price": row.unit_price,
        "discount_amount": row.discount_amount,
        "status": row.status,
    }


def import_rows(engine: Engine, rows: list[ParsedRow]) -> tuple[int, int]:
    """Insert rows idempotently. Returns (skipped_existing, inserted)."""
    with engine.begin() as connection:
        existing: set[str] = set()
        ids = [row.transaction_id for row in rows]

        for chunk in _chunked(ids, BATCH_SIZE):
            statement = select(SalesTransaction.transaction_id).where(
                SalesTransaction.transaction_id.in_(chunk)
            )
            existing.update(connection.execute(statement).scalars().all())

        new_rows = [row for row in rows if row.transaction_id not in existing]
        payload = [row_payload(row) for row in new_rows]

        for chunk in _chunked(payload, BATCH_SIZE):
            connection.execute(insert(SalesTransaction.__table__), chunk)

    return len(existing), len(new_rows)


def write_rejections(path: Path, rejected: list[RejectedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["row_number", "transaction_id", "reason", "raw_row"],
        )
        writer.writeheader()
        for row in rejected:
            writer.writerow(
                {
                    "row_number": row.row_number,
                    "transaction_id": row.transaction_id,
                    "reason": row.reason,
                    "raw_row": json.dumps(row.raw, ensure_ascii=False),
                }
            )


def _date_coverage(rows: list[ParsedRow]) -> tuple[date | None, date | None]:
    if not rows:
        return None, None
    dates = [row.order_date for row in rows]
    return min(dates), max(dates)


def print_summary(
    *,
    csv_path: Path,
    extra_headers: list[str],
    parsed: list[ParsedRow],
    rejected: list[RejectedRow],
    warnings: list[str],
    skipped: int,
    imported: int,
    rejections_path: Path,
) -> None:
    status_counts = Counter(row.status for row in parsed)
    start, end = _date_coverage(parsed)

    print(f"CSV: {csv_path}")
    if extra_headers:
        print(
            "Ignored extra columns: " + ", ".join(extra_headers)
        )
    print(f"Rows read: {len(parsed) + len(rejected)}")
    print(f"Valid rows: {len(parsed)}")
    print(f"Imported: {imported}")
    print(f"Skipped (already present): {skipped}")
    print(f"Rejected: {len(rejected)}")
    print(f"Warnings: {len(warnings)}")
    if status_counts:
        print(
            "Status counts (valid rows): "
            + ", ".join(
                f"{status}={count}"
                for status, count in sorted(status_counts.items())
            )
        )
    if start and end:
        print(f"Date coverage (valid rows): {start.isoformat()} to {end.isoformat()}")
    print(f"Rejection report: {rejections_path}")

    if warnings:
        print("Warning details (first 10):")
        for warning in warnings[:10]:
            print(f"  - {warning}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import the sales CSV into PostgreSQL idempotently."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--rejections",
        type=Path,
        default=None,
        help="Path for the rejection CSV (default: next to the source CSV).",
    )
    args = parser.parse_args(argv)

    csv_path = args.csv_path.resolve()
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 2

    try:
        _, extra_headers, rows = read_csv(csv_path)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Import aborted: {exc}", file=sys.stderr)
        return 2

    parsed, rejected, warnings = parse_rows(rows)

    rejections_path = (
        args.rejections.resolve()
        if args.rejections
        else csv_path.parent / "import_rejections.csv"
    )
    if rejections_path == csv_path:
        print(
            "Refusing to overwrite the source CSV with the rejection report.",
            file=sys.stderr,
        )
        return 2

    try:
        write_rejections(rejections_path, rejected)
    except OSError as exc:
        print(f"Could not write rejection report: {exc}", file=sys.stderr)
        return 2

    try:
        engine = get_admin_engine()
        skipped, imported = import_rows(engine, parsed)
    except RuntimeError as exc:
        print(f"Import aborted: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        first_line = str(exc).splitlines()[0] if str(exc) else ""
        print(
            f"Import failed ({exc.__class__.__name__}): {first_line[:300]}",
            file=sys.stderr,
        )
        print(
            "Ensure the schema is initialized with db/schema.sql and "
            "DATABASE_ADMIN_URL is correct.",
            file=sys.stderr,
        )
        return 1

    print_summary(
        csv_path=csv_path,
        extra_headers=extra_headers,
        parsed=parsed,
        rejected=rejected,
        warnings=warnings,
        skipped=skipped,
        imported=imported,
        rejections_path=rejections_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
