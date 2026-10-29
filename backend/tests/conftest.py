from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.business_rules import ParsedRow  # noqa: E402
from app.config import Settings  # noqa: E402
from app.import_csv import import_rows  # noqa: E402
from app.models import Base  # noqa: E402


def _row(
    number: int,
    transaction_id: str,
    order_date: date,
    product: str,
    category: str,
    region: str,
    channel: str,
    quantity: int,
    unit_price: str,
    discount: str,
    status: str,
) -> ParsedRow:
    return ParsedRow(
        row_number=number,
        transaction_id=transaction_id,
        order_date=order_date,
        product=product,
        category=category,
        region=region,
        sales_channel=channel,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        discount_amount=Decimal(discount),
        status=status,
    )


@pytest.fixture()
def sample_rows() -> list[ParsedRow]:
    return [
        _row(
            2,
            "T1",
            date(2026, 1, 5),
            "Widget",
            "Electronics",
            "North",
            "Online",
            2,
            "100.00",
            "10.00",
            "completed",
        ),
        _row(
            3,
            "T2",
            date(2026, 1, 10),
            "Widget",
            "Electronics",
            "South",
            "Retail",
            1,
            "100.00",
            "0.00",
            "completed",
        ),
        _row(
            4,
            "T3",
            date(2026, 2, 3),
            "Gadget",
            "Furniture",
            "North",
            "Online",
            3,
            "50.00",
            "5.00",
            "completed",
        ),
        _row(
            5,
            "T4",
            date(2026, 2, 14),
            "Gadget",
            "Furniture",
            "South",
            "Retail",
            2,
            "50.00",
            "0.00",
            "completed",
        ),
        _row(
            6,
            "T5",
            date(2026, 3, 1),
            "Widget",
            "Electronics",
            "North",
            "Online",
            1,
            "100.00",
            "0.00",
            "returned",
        ),
        _row(
            7,
            "T6",
            date(2026, 4, 1),
            "Gizmo",
            "Accessories",
            "West",
            "Online",
            0,
            "75.00",
            "0.00",
            "completed",
        ),
        _row(
            8,
            "T7",
            date(2026, 5, 1),
            "Widget",
            "Electronics",
            "East",
            "Retail",
            1,
            "100.00",
            "0.00",
            "completed",
        ),
    ]


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture()
def seeded_engine(engine, sample_rows):
    import_rows(engine, sample_rows)
    return engine


@pytest.fixture()
def seeded_session(seeded_engine):
    with Session(seeded_engine) as session:
        yield session


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite://",
        database_admin_url="sqlite+pysqlite://",
        groq_api_key="",
        groq_model="",
        frontend_url="http://localhost:5173",
        currency_code="",
    )


@pytest.fixture()
def client(monkeypatch, seeded_engine, test_settings):
    from app import api as api_module

    @contextmanager
    def test_session():
        with Session(seeded_engine) as session:
            yield session

    monkeypatch.setattr(api_module, "runtime_session", test_session)
    monkeypatch.setattr(api_module, "get_settings", lambda: test_settings)

    app = FastAPI()
    app.include_router(api_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client
