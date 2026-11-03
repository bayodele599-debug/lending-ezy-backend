"""Opt-in customer accounts, verified-email sessions, and durable financing plans.

This module never offers or approves credit. Tokens are one-use / hashed in DB;
customer sessions are bound to an authenticated principal.
"""
import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, select, func
from sqlalchemy.orm import Mapped, Session, mapped_column
from .config import APP_ENV
from .db import Base, get_db

router = APIRouter(prefix="/api/v1/account", tags=["customer accounts"])
CURRENCIES = {"USD", "GBP", "EUR", "CAD", "AUD", "SGD", "NGN", "ZAR", "INR", "AED", "KES", "GHS"}
TERMS = {6, 12, 18, 24, 36, 48, 60}
ITERATIONS = 390_000


def now():
    return datetime.now(timezone.utc)


def guard():
    if os.getenv("CUSTOMER_ACCOUNTS_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Customer accounts are not available yet")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    salt = secrets.token_bytes(24)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONS, salt.hex(), key.hex())


def password_matches(password, encoded):
    try:
        scheme, count, salt, wanted = encoded.split("$")
        count = int(count)
        if scheme != "pbkdf2_sha256" or not (200_000 <= count <= 1_500_000):
            return False
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), count)
        return hmac.compare_digest(key, bytes.fromhex(wanted))
    except (TypeError, ValueError):
        return False


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    password_digest: Mapped[str] = mapped_column(String(250), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class CustomerSession(Base):
    __tablename__ = "customer_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class AccountToken(Base):
    __tablename__ = "account_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class CustomerPlan(Base):
    __tablename__ = "customer_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class RegisterInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    country: str = Field(pattern=r"^[A-Z]{2}$")
    password: str = Field(min_length=12, max_length=128)
    consent_to_terms: bool


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EmailInput(BaseModel):
    email: EmailStr


class TokenInput(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class ResetInput(TokenInput):
    password: str = Field(min_length=12, max_length=128)


class ProfileInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    country: str = Field(pattern=r"^[A-Z]{2}$")


class PlanInput(BaseModel):
    id: UUID | None = None
    type: Literal["personal", "business"]
    purpose: str = Field(min_length=2, max_length=80)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    currency: str
    amount: Decimal = Field(ge=500, le=10000000, max_digits=12, decimal_places=2)
    months: int
    annual_rate: Decimal = Field(ge=0, le=40, max_digits=5, decimal_places=2)

    @field_validator("currency")
    @classmethod
    def good_currency(cls, value):
        if value not in CURRENCIES:
            raise ValueError("Unsupported currency")
        return value

    @field_validator("months")
    @classmethod
    def good_term(cls, value):
        if value not in TERMS:
            raise ValueError("Unsupported repayment term")
        return value


def public_customer(c):
    return {"id": c.id, "email": c.email, "full_name": c.full_name, "country": c.country,
            "verified": bool(c.email_verified_at), "created_at": c.created_at.isoformat()}


def public_plan(p):
    return {"id": p.id, "type": p.type, "purpose": p.purpose, "country": p.country,
            "currency": p.currency, "amount": str(p.amount), "months": p.months,
            "annual_rate": str(p.annual_rate), "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat()}


def deliver_email(address, subject, body):
    host, sender = os.getenv("SMTP_HOST"), os.getenv("SMTP_FROM")
    if not host or not sender:
        if APP_ENV == "development":
            return  # tests replace this function; production must configure SMTP
        raise RuntimeError("Email not configured")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, address, subject
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = os.getenv("SMTP_SSL", "false").lower() == "true"
    smtp = (smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=10)
            if use_ssl else smtplib.SMTP(host, port, timeout=10))
    with smtp:
        if not use_ssl and os.getenv("SMTP_STARTTLS", "true").lower() == "true":
            smtp.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD"):
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def create_token(db, customer, kind):
    for row in db.scalars(select(AccountToken).where(
            AccountToken.customer_id == customer.id, AccountToken.kind == kind,
            AccountToken.used_at.is_(None))):
        row.used_at = now()
    raw = secrets.token_urlsafe(40)
    db.add(AccountToken(customer_id=customer.id, kind=kind, token_digest=digest(raw),
                        expires_at=now() + timedelta(hours=24 if kind == "verify" else 1)))
    return raw


def send_token(customer, kind, token):
    base = os.getenv("CUSTOMER_FRONTEND_URL", "http://localhost:3000").rstrip("/")
    path = "/account/verify" if kind == "verify" else "/account/reset"
    url = base + path + "?token=" + quote(token)
    deliver_email(customer.email,
                  "Verify your Lending Ezy email" if kind == "verify" else "Reset your Lending Ezy password",
                  "Open the link below to continue:\n\n" + url +
                  "\n\nIgnore this email if you didn't request it. No credit decision is made.")


def consume(db, token, kind):
    row = db.scalar(select(AccountToken).where(AccountToken.token_digest == digest(token),
                                               AccountToken.kind == kind, AccountToken.used_at.is_(None)))
    if not row or row.expires_at.replace(tzinfo=timezone.utc) < now():
        raise HTTPException(400, "Link is invalid or expired")
    customer = db.get(Customer, row.customer_id)
    if not customer:
        raise HTTPException(400, "Link is invalid or expired")
    row.used_at = now()
    return customer


def require_customer(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Customer:
    guard()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required")
    raw = authorization[7:]
    if not 32 <= len(raw) <= 256:
        raise HTTPException(401, "Sign in required")
    row = db.scalar(select(CustomerSession).where(
        CustomerSession.token_digest == digest(raw), CustomerSession.revoked_at.is_(None)))
    if not row or row.expires_at.replace(tzinfo=timezone.utc) < now():
        raise HTTPException(401, "Session expired or invalid")
    customer = db.get(Customer, row.customer_id)
    if not customer or not customer.email_verified_at:
        raise HTTPException(401, "Sign in required")
    return customer


def optional_customer(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Customer | None:
    if not authorization:
        return None
    return require_customer(authorization, db)


@router.post("/register", status_code=201, dependencies=[Depends(guard)])
def register(data: RegisterInput, db: Session = Depends(get_db)):
    if not data.consent_to_terms:
        raise HTTPException(422, "Accept the privacy notice and terms to continue")
    if APP_ENV != "development" and not (os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM")):
        raise HTTPException(503, "Email verification is not configured")
    email = str(data.email).strip().lower()
    if db.scalar(select(Customer).where(Customer.email == email)):
        return {"message": "If the email is eligible, verification instructions will be sent."}
    row = Customer(email=email, full_name=data.full_name.strip(), country=data.country,
                   password_digest=password_hash(data.password))
    db.add(row)
    db.flush()
    raw = create_token(db, row, "verify")
    db.commit()
    try:
        send_token(row, "verify", raw)
    except Exception:
        raise HTTPException(503, "Account saved; email could not be sent. Request another verification link.")
    return {"message": "Check your inbox to verify your email."}


@router.post("/resend-verification", dependencies=[Depends(guard)])
def resend_verification(data: EmailInput, db: Session = Depends(get_db)):
    row = db.scalar(select(Customer).where(Customer.email == str(data.email).lower()))
    if row and not row.email_verified_at:
        recent = db.scalar(select(AccountToken).where(
            AccountToken.customer_id == row.id, AccountToken.kind == "verify",
            AccountToken.created_at >= now()-timedelta(minutes=3)))
        if not recent:
            raw = create_token(db, row, "verify")
            db.commit()
            try: send_token(row, "verify", raw)
            except Exception: pass
    return {"message": "If the account is pending, a verification email will be sent."}


@router.post("/verify-email", dependencies=[Depends(guard)])
def verify(data: TokenInput, db: Session = Depends(get_db)):
    row = consume(db, data.token, "verify")
    row.email_verified_at = now()
    row.updated_at = now()
    db.commit()
    return {"message": "Email verified. You may sign in."}


@router.post("/login", dependencies=[Depends(guard)])
def login(data: LoginInput, db: Session = Depends(get_db)):
    row = db.scalar(select(Customer).where(Customer.email == str(data.email).lower()))
    # Constant work on unknown email also reduces enumeration by timing.
    encoded = row.password_digest if row else password_hash("non-existent-account")
    valid = password_matches(data.password, encoded)
    if row and row.locked_until and row.locked_until.replace(tzinfo=timezone.utc) > now():
        raise HTTPException(429, "Too many sign-in attempts. Try again later.")
    if not row or not valid:
        if row:
            row.failed_logins += 1
            if row.failed_logins >= 6:
                row.locked_until = now() + timedelta(minutes=15)
                row.failed_logins = 0
            db.commit()
        raise HTTPException(401, "Invalid email or password")
    if not row.email_verified_at:
        raise HTTPException(403, "Verify your email before signing in")
    row.failed_logins = 0
    row.locked_until = None
    raw = secrets.token_urlsafe(48)
    db.add(CustomerSession(customer_id=row.id,token_digest=digest(raw),
                           expires_at=now()+timedelta(days=14)))
    db.commit()
    return {"token": raw, "expires_in": 14*86400, "customer": public_customer(row)}


@router.post("/password/request-reset", dependencies=[Depends(guard)])
def request_reset(data: EmailInput, db: Session = Depends(get_db)):
    row = db.scalar(select(Customer).where(Customer.email == str(data.email).lower()))
    if row:
        recent = db.scalar(select(AccountToken).where(
            AccountToken.customer_id == row.id, AccountToken.kind == "reset",
            AccountToken.created_at >= now()-timedelta(minutes=3)))
        if not recent:
            raw = create_token(db, row, "reset")
            db.commit()
            try: send_token(row, "reset", raw)
            except Exception: pass
    return {"message": "If the account exists, reset instructions will be sent."}


@router.post("/password/reset", dependencies=[Depends(guard)])
def reset(data: ResetInput, db: Session = Depends(get_db)):
    row = consume(db, data.token, "reset")
    row.password_digest = password_hash(data.password)
    row.updated_at = now()
    row.failed_logins = 0
    row.locked_until = None
    for session in db.scalars(select(CustomerSession).where(CustomerSession.customer_id == row.id)):
        session.revoked_at = now()
    db.commit()
    return {"message": "Password reset. Sign in again."}


@router.post("/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if authorization and authorization.startswith("Bearer "):
        row = db.scalar(select(CustomerSession).where(
            CustomerSession.token_digest == digest(authorization[7:])))
        if row:
            row.revoked_at = now()
            db.commit()
    return {"message": "Signed out"}


@router.get("/me")
def me(customer: Customer = Depends(require_customer)):
    return public_customer(customer)


@router.patch("/me")
def profile(data: ProfileInput, customer: Customer = Depends(require_customer),
            db: Session = Depends(get_db)):
    customer.full_name = data.full_name.strip()
    customer.country = data.country
    customer.updated_at = now()
    db.commit()
    return public_customer(customer)


@router.get("/plans")
def plans(customer: Customer = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(CustomerPlan).where(CustomerPlan.customer_id == customer.id)
                      .order_by(CustomerPlan.updated_at.desc()).limit(100)).all()
    return {"plans": [public_plan(x) for x in rows]}


@router.post("/plans", status_code=201)
def save_plan(data: PlanInput, customer: Customer = Depends(require_customer),
              db: Session = Depends(get_db)):
    count = db.scalar(select(func.count(CustomerPlan.id)).where(CustomerPlan.customer_id == customer.id)) or 0
    if count >= 100:
        raise HTTPException(409, "100-plan limit reached")
    if data.id and db.get(CustomerPlan, str(data.id)):
        raise HTTPException(409, "Plan already exists")
    row = CustomerPlan(id=str(data.id or uuid4()), customer_id=customer.id, type=data.type,
                       purpose=data.purpose.strip(), country=data.country, currency=data.currency,
                       amount=data.amount, months=data.months, annual_rate=data.annual_rate)
    db.add(row)
    db.commit()
    db.refresh(row)
    return public_plan(row)


@router.patch("/plans/{plan_id}")
def edit_plan(plan_id: UUID, data: PlanInput, customer: Customer = Depends(require_customer),
              db: Session = Depends(get_db)):
    row = db.get(CustomerPlan, str(plan_id))
    if not row or row.customer_id != customer.id:
        raise HTTPException(404, "Plan not found")
    if data.id and str(data.id) != row.id:
        raise HTTPException(422, "Plan identifier cannot change")
    row.type, row.purpose, row.country, row.currency = data.type, data.purpose.strip(), data.country, data.currency
    row.amount, row.months, row.annual_rate = data.amount, data.months, data.annual_rate
    row.updated_at = now()
    db.commit()
    return public_plan(row)


@router.delete("/plans/{plan_id}")
def remove_plan(plan_id: UUID, customer: Customer = Depends(require_customer),
                db: Session = Depends(get_db)):
    row = db.get(CustomerPlan, str(plan_id))
    if not row or row.customer_id != customer.id:
        raise HTTPException(404, "Plan not found")
    db.delete(row)
    db.commit()
    return {"deleted": True}



@router.get("/export")
def export_account(customer: Customer = Depends(require_customer),
                   db: Session = Depends(get_db)):
    """Explicit subject-access download; excludes secrets and staff-only notes."""
    from .requests import FinancingRequest, RequestMessage, public_summary, visible_message
    plans = db.scalars(select(CustomerPlan).where(CustomerPlan.customer_id == customer.id)
                       .order_by(CustomerPlan.created_at.desc())).all()
    cases = db.scalars(select(FinancingRequest).where(
        FinancingRequest.customer_id == customer.id)
        .order_by(FinancingRequest.created_at.desc())).all()
    items = []
    for case in cases:
        visible = db.scalars(select(RequestMessage).where(
            RequestMessage.request_id == case.id)
            .order_by(RequestMessage.created_at.asc())).all()
        items.append({"request": public_summary(case),
                      "conversation": [visible_message(message) for message in visible]})
    return {"exported_at": now().isoformat(),
            "account": public_customer(customer),
            "account_plans": [public_plan(plan) for plan in plans],
            "account_linked_requests": items,
            "notice": "Browser-only plans and anonymous submissions are not included. Internal staff notes are not part of the customer conversation."}
