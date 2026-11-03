"""Consent-based financing requests, with an auditable human-operated review queue.

This is intake and manual case management, not automated credit underwriting.
Only a licensed lender can ultimately issue a binding credit offer.
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db
from .finance import amortize
from .inquiries import notify_admin, require_admin, verify_turnstile
from .accounts import Customer, optional_customer, require_customer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["financing requests"])

CURRENCIES = {"USD", "GBP", "EUR", "CAD", "AUD", "SGD", "NGN", "ZAR", "INR", "AED", "KES", "GHS"}
TERMS = {6, 12, 18, 24, 36, 48, 60}
TYPES = Literal["personal", "business"]
STATES = Literal["submitted", "in_review", "needs_information", "proceed_to_next_stage", "not_proceeding", "closed"]
TRANSITIONS = {
    "submitted": {"in_review", "needs_information", "not_proceeding", "closed"},
    "in_review": {"needs_information", "proceed_to_next_stage", "not_proceeding", "closed"},
    "needs_information": {"in_review", "not_proceeding", "closed"},
    "proceed_to_next_stage": {"in_review", "closed"},
    "not_proceeding": {"in_review", "closed"},
    "closed": {"in_review"},
}


def now():
    return datetime.now(timezone.utc)


class FinancingRequest(Base):
    __tablename__ = "financing_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    client_token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(150))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    term_months: Mapped[int] = mapped_column(nullable=False)
    assumed_annual_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class RequestEvent(Base):
    __tablename__ = "financing_request_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id: Mapped[str] = mapped_column(ForeignKey("financing_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(50), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class RequestMessage(Base):
    __tablename__ = "financing_request_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id: Mapped[str] = mapped_column(ForeignKey("financing_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


Index("ix_financing_request_status_created", FinancingRequest.status, FinancingRequest.created_at)


class RequestInput(BaseModel):
    client_token: UUID
    kind: TYPES
    purpose: str = Field(min_length=2, max_length=80)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    currency: str
    amount: Decimal = Field(ge=Decimal("500"), le=Decimal("10000000"), max_digits=12, decimal_places=2)
    term_months: int
    assumed_annual_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("40"), max_digits=5, decimal_places=2)
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    business_name: str | None = Field(default=None, max_length=150)
    message: str | None = Field(default=None, max_length=1500)
    consent_to_contact: bool
    confirms_estimate_only: bool
    website: str = Field(default="", max_length=150)  # honeypot
    turnstile_token: str | None = None

    @field_validator("name", "purpose")
    @classmethod
    def strip_required(cls, value: str):
        return value.strip()

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str):
        if value not in CURRENCIES:
            raise ValueError("Unsupported currency")
        return value

    @field_validator("term_months")
    @classmethod
    def valid_term(cls, value: int):
        if value not in TERMS:
            raise ValueError("Unsupported term")
        return value

    @model_validator(mode="after")
    def valid_consent(self):
        if len(self.name) < 2 or len(self.purpose) < 2:
            raise ValueError("Name and purpose are required")
        if not self.consent_to_contact or not self.confirms_estimate_only:
            raise ValueError("Consent and acknowledgement are required")
        if self.kind == "business" and (not self.business_name or len(self.business_name.strip()) < 2):
            raise ValueError("Business name is required")
        return self


class ReviewInput(BaseModel):
    status: STATES
    expected_status: STATES
    note: str = Field(min_length=3, max_length=3000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Reason must contain at least three characters")
        return value


class MessageInput(BaseModel):
    body: str = Field(min_length=2, max_length=2000)

    @field_validator("body")
    @classmethod
    def clean_body(cls, value: str):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Message is too short")
        return value


def visible_message(msg: RequestMessage):
    return {"id": msg.id, "author": msg.author, "body": msg.body,
            "created_at": msg.created_at.isoformat()}


def require_owned_request(db: Session, customer: Customer, request_id: UUID) -> FinancingRequest:
    item = db.get(FinancingRequest, str(request_id))
    if item is None or item.customer_id != customer.id:
        raise HTTPException(404, "Request not found")
    return item


def append_message(db: Session, item: FinancingRequest, author: str, body: str):
    recent = db.scalar(select(RequestMessage).where(
        RequestMessage.request_id == item.id, RequestMessage.author == author)
        .order_by(RequestMessage.created_at.desc()).limit(1))
    if recent and recent.created_at.replace(tzinfo=timezone.utc) > now() - timedelta(seconds=5):
        raise HTTPException(429, "Please allow a moment between messages")
    count = db.scalar(select(func.count(RequestMessage.id)).where(
        RequestMessage.request_id == item.id)) or 0
    if count >= 200:
        raise HTTPException(409, "Message thread limit reached; contact support")
    msg = RequestMessage(request_id=item.id, author=author, body=body)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return visible_message(msg)


def normalize(data: RequestInput):
    """Canonical form for idempotency, excluding bot token and honeypot."""
    return {
        "kind": data.kind,
        "purpose": data.purpose,
        "country": data.country,
        "currency": data.currency,
        "amount": str(data.amount),
        "term_months": data.term_months,
        "assumed_annual_rate": str(data.assumed_annual_rate),
        "name": data.name,
        "email": str(data.email).strip().lower(),
        "business_name": data.business_name.strip() if data.business_name else None,
        "message": data.message.strip() if data.message else None,
        "consent_to_contact": data.consent_to_contact,
        "confirms_estimate_only": data.confirms_estimate_only,
    }


def digest_for(fields):
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def public_summary(item: FinancingRequest):
    return {
        "id": item.id,
        "reference": item.id,
        "status": item.status,
        "name": item.name,
        "email": item.email,
        "country": item.country,
        "kind": item.kind,
        "purpose": item.purpose,
        "business_name": item.business_name,
        "currency": item.currency,
        "amount": str(item.amount),
        "term_months": item.term_months,
        "assumed_annual_rate": str(item.assumed_annual_rate),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def admin_summary(item: FinancingRequest):
    fields = public_summary(item)
    fields["message"] = item.message
    fields["consent_at"] = item.consent_at.isoformat()
    fields["estimate"] = {
        key: value for key, value in amortize(item.amount, int(item.assumed_annual_rate * 100), item.term_months).items()
        if key in {"monthly_payment", "total_interest", "total_repayment"}
    }
    return fields


@router.post("/financing-requests", status_code=201)
def submit_financing_request(data: RequestInput, request: Request, tasks: BackgroundTasks,
                             db: Session = Depends(get_db),
                             customer: Customer | None = Depends(optional_customer)):
    if os.getenv("PUBLIC_FINANCING_REQUESTS_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Financing request intake is temporarily unavailable")

    fields = normalize(data)
    if customer and customer.email != fields["email"]:
        raise HTTPException(403, "Sign in with the same email used on this request")
    digest = digest_for(fields)
    token = str(data.client_token)
    existing = db.scalar(select(FinancingRequest).where(FinancingRequest.client_token == token))
    if existing:
        if existing.payload_digest != digest:
            raise HTTPException(409, "This submission reference is already in use")
        return {"received": True, "reference": existing.id, "status": existing.status}

    verify_turnstile(data.turnstile_token, request)
    if data.website.strip():
        # Do not store automated spam, or return a real case reference.
        return {"received": True, "reference": None, "status": "received"}

    window = now() - timedelta(hours=24)
    count = db.scalar(select(func.count(FinancingRequest.id)).where(
        FinancingRequest.email == fields["email"], FinancingRequest.created_at >= window
    )) or 0
    if count >= 3:
        raise HTTPException(429, "Please contact our team before submitting more requests")

    item = FinancingRequest(
        client_token=token, payload_digest=digest, customer_id=customer.id if customer else None,
        kind=fields["kind"], purpose=fields["purpose"], country=fields["country"],
        currency=fields["currency"], amount=data.amount, term_months=data.term_months,
        assumed_annual_rate=data.assumed_annual_rate, name=fields["name"],
        email=fields["email"], business_name=fields["business_name"], message=fields["message"],
        consent_at=now(), status="submitted"
    )
    db.add(item)
    db.flush()
    db.add(RequestEvent(request_id=item.id, old_status=None, new_status="submitted",
                        actor="customer", note="Consent-based financing request received"))
    db.commit()
    db.refresh(item)
    tasks.add_task(notify_admin, item.id, "financing request")
    return {"received": True, "reference": item.id, "status": "submitted"}


@router.get("/admin/financing-requests", dependencies=[Depends(require_admin)])
def list_requests(status: STATES | None = None, kind: TYPES | None = None,
                  limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    limit = max(1, min(100, limit))
    offset = max(0, min(offset, 10000))
    statement = select(FinancingRequest)
    if status:
        statement = statement.where(FinancingRequest.status == status)
    if kind:
        statement = statement.where(FinancingRequest.kind == kind)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.order_by(FinancingRequest.created_at.desc()).offset(offset).limit(limit)).all()
    return {"requests": [admin_summary(x) for x in items], "total": total, "limit": limit, "offset": offset}


@router.get("/admin/financing-requests/{request_id}", dependencies=[Depends(require_admin)])
def request_detail(request_id: UUID, db: Session = Depends(get_db)):
    item = db.get(FinancingRequest, str(request_id))
    if item is None:
        raise HTTPException(404, "Financing request not found")
    history = db.scalars(select(RequestEvent).where(RequestEvent.request_id == item.id)
                         .order_by(RequestEvent.created_at.asc(), RequestEvent.id.asc())).all()
    return {
        "request": admin_summary(item),
        "history": [{
            "id": event.id, "old_status": event.old_status, "new_status": event.new_status,
            "actor": event.actor, "note": event.note, "created_at": event.created_at.isoformat()
        } for event in history]
    }


@router.patch("/admin/financing-requests/{request_id}", dependencies=[Depends(require_admin)])
def review_request(request_id: UUID, data: ReviewInput, db: Session = Depends(get_db)):
    item = db.get(FinancingRequest, str(request_id))
    if item is None:
        raise HTTPException(404, "Financing request not found")
    if item.status != data.expected_status:
        raise HTTPException(409, "This request was updated by another operator; refresh before reviewing")
    if data.status not in TRANSITIONS.get(item.status, set()):
        raise HTTPException(422, "Invalid review status transition")
    previous = item.status
    stamp = now()
    # Compare-and-swap also protects against concurrent operator decisions.
    result = db.execute(update(FinancingRequest).where(
        FinancingRequest.id == item.id,
        FinancingRequest.status == previous
    ).values(status=data.status, updated_at=stamp))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Request changed during review; refresh and retry")
    db.add(RequestEvent(request_id=item.id, old_status=previous, new_status=data.status,
                        actor="admin", note=data.note))
    db.commit()
    return {"reference": item.id, "status": data.status, "previous_status": previous, "updated_at": stamp.isoformat()}



# A logged-in customer sees only cases explicitly submitted with their bearer
# token. Previously submitted anonymous cases are never claimed by matching email.
@router.get("/account/requests")
def account_requests(customer: Customer = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(FinancingRequest).where(
        FinancingRequest.customer_id == customer.id)
        .order_by(FinancingRequest.created_at.desc()).limit(100)).all()
    return {"requests": [public_summary(x) for x in rows]}


@router.get("/account/requests/{request_id}/messages")
def customer_messages(request_id: UUID, customer: Customer = Depends(require_customer),
                      db: Session = Depends(get_db)):
    item = require_owned_request(db, customer, request_id)
    rows = db.scalars(select(RequestMessage).where(RequestMessage.request_id == item.id)
                      .order_by(RequestMessage.created_at.asc())).all()
    return {"messages": [visible_message(x) for x in rows],
            "reference": item.id, "status": item.status}


@router.post("/account/requests/{request_id}/messages", status_code=201)
def customer_reply(request_id: UUID, payload: MessageInput,
                   customer: Customer = Depends(require_customer), db: Session = Depends(get_db)):
    item = require_owned_request(db, customer, request_id)
    if item.status == "closed":
        raise HTTPException(409, "This request is closed")
    return append_message(db, item, "customer", payload.body)


@router.get("/admin/financing-requests/{request_id}/messages", dependencies=[Depends(require_admin)])
def admin_messages(request_id: UUID, db: Session = Depends(get_db)):
    item = db.get(FinancingRequest, str(request_id))
    if not item:
        raise HTTPException(404, "Request not found")
    rows = db.scalars(select(RequestMessage).where(RequestMessage.request_id == item.id)
                      .order_by(RequestMessage.created_at.asc())).all()
    return {"messages": [visible_message(x) for x in rows],
            "reference": item.id, "has_customer_account": item.customer_id is not None}


@router.post("/admin/financing-requests/{request_id}/messages",
             status_code=201, dependencies=[Depends(require_admin)])
def admin_reply(request_id: UUID, payload: MessageInput, db: Session = Depends(get_db)):
    item = db.get(FinancingRequest, str(request_id))
    if not item:
        raise HTTPException(404, "Request not found")
    if item.customer_id is None:
        raise HTTPException(409, "This request was submitted without a customer account; use the contact inbox")
    return append_message(db, item, "admin", payload.body)
