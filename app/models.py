from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import DateTime, Integer, String, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class DemoApplication(Base):
    """Non-identifying test record. Not a real loan application."""
    __tablename__ = "sandbox_applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_id: Mapped[str] = mapped_column(String(60), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    annual_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="sandbox_submitted", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
