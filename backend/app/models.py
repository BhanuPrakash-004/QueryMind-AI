"""SQLAlchemy models for the sales analytics database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Integer, Numeric, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SalesTransaction(Base):
    __tablename__ = "sales_transactions"

    transaction_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    product: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    category: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    region: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    sales_channel: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    __table_args__ = (
        CheckConstraint(
            "quantity >= 0", name="ck_sales_quantity_nonnegative"
        ),
        CheckConstraint(
            "unit_price >= 0", name="ck_sales_unit_price_nonnegative"
        ),
        CheckConstraint(
            "discount_amount >= 0", name="ck_sales_discount_nonnegative"
        ),
    )
