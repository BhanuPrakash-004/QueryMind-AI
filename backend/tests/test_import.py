from __future__ import annotations

from sqlalchemy import func, select

from app.import_csv import import_rows, parse_rows, read_csv
from app.models import SalesTransaction

HEADERS = (
    "Transaction_Id,Order_date,Product,Category,Region,Sales_channel,"
    "Quantity,Unit_price,Discount_amount,Status\n"
)

BASE_ROW = {
    "Transaction_Id": "T1",
    "Order_date": "05-01-2026",
    "Product": "Widget",
    "Category": "Electronics",
    "Region": "North",
    "Sales_channel": "Online",
    "Quantity": "2",
    "Unit_price": "100.00",
    "Discount_amount": "10.00",
    "Status": "Completed",
}


def test_valid_csv_import_is_idempotent(engine, tmp_path):
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        HEADERS
        + "T1,05-01-2026,Widget,Electronics,North,Online,2,100.00,10.00,Completed\n"
        + "T2,10-01-2026,Gadget,Furniture,South,Retail,1,50.00,0,Completed\n",
        encoding="utf-8",
    )

    headers, extra, rows = read_csv(csv_path)
    parsed, rejected, warnings = parse_rows(rows)

    assert headers == [
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
    ]
    assert extra == []
    assert len(parsed) == 2
    assert rejected == []
    assert warnings == []

    skipped, inserted = import_rows(engine, parsed)
    assert (skipped, inserted) == (0, 2)

    skipped, inserted = import_rows(engine, parsed)
    assert (skipped, inserted) == (2, 0)

    with engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(SalesTransaction)
        ).scalar_one()
    assert count == 2


def test_invalid_date_and_numeric_records_are_rejected():
    rows = [
        (2, {**BASE_ROW, "Order_date": "2026-01-05"}),
        (3, {**BASE_ROW, "Transaction_Id": "T2", "Unit_price": "abc"}),
        (4, {**BASE_ROW, "Transaction_Id": "T3", "Quantity": "1.5"}),
        (
            5,
            {
                **BASE_ROW,
                "Transaction_Id": "T4",
                "Discount_amount": "250.00",
            },
        ),
    ]

    parsed, rejected, _ = parse_rows(rows)

    assert parsed == []
    assert len(rejected) == 4
    reasons = " ".join(row.reason for row in rejected)
    assert "expected DD-MM-YYYY" in reasons
    assert "invalid unit_price" in reasons
    assert "invalid quantity" in reasons
    assert "exceeds gross sales" in reasons


def test_duplicate_transaction_ids_are_rejected():
    rows = [
        (2, {**BASE_ROW}),
        (3, {**BASE_ROW}),
    ]

    parsed, rejected, _ = parse_rows(rows)

    assert len(parsed) == 1
    assert len(rejected) == 1
    assert "duplicate transaction_id" in rejected[0].reason
