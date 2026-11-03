"""Contact intake and a secured admin mailbox. Not a loan application."""
import hashlib
import hmac
import json
import logging
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import DateTime, ForeignKey, String, Text, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from .config import APP_ENV
from .db import Base, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["inquiries"])

class Inquiry(Base):
    __tablename__ = "contact_inquiries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    product_interest: Mapped[str | None] = mapped_column(String(50), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(150), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False, index=True)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class InquiryReply(Base):
    __tablename__ = "inquiry_replies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("contact_inquiries.id"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class InquiryInput(BaseModel):
    kind: Literal["borrower", "partner"]
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    country: str = Field(pattern=r"^[A-Z]{2}$")
    product_interest: Literal["personal", "business", "salary_advance", "other"] | None = None
    institution: str | None = Field(default=None, max_length=150)
    message: str | None = Field(default=None, max_length=1500)
    consent_to_contact: bool
    website: str = Field(default="", max_length=150) # honeypot
    turnstile_token: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter a name")
        return value

    @model_validator(mode="after")
    def check_form(self):
        if not self.consent_to_contact:
            raise ValueError("Consent to receive a response is required")
        if self.kind == "partner" and (not self.institution or len(self.institution.strip()) < 2):
            raise ValueError("Business name is required")
        return self

class ReplyInput(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    action: Literal["save_draft", "send"] = "save_draft"

    @field_validator("body")
    @classmethod
    def clean_body(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("Enter reply text")
        return value

class StatusUpdate(BaseModel):
    status: Literal["new", "in_progress", "replied", "closed"]

def require_admin(x_admin_key: str | None = Header(default=None)):
    configured = os.getenv("ADMIN_API_TOKEN", "")
    if len(configured) < 32:
        raise HTTPException(503, "Admin access not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        raise HTTPException(401, "Unauthorized")
    return True

def verify_turnstile(token: str | None, request: Request):
    if APP_ENV == "development":
        return
    secret = os.getenv("TURNSTILE_SECRET_KEY", "")
    if not secret or not token:
        raise HTTPException(503, "Bot protection is not configured")
    form = urlencode({"secret": secret, "response": token, "remoteip": request.client.host if request.client else ""}).encode()
    try:
        req = UrlRequest("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=form, method="POST")
        with urlopen(req, timeout=5) as r:
            result = json.load(r)
    except Exception:
        raise HTTPException(503, "Unable to verify submission")
    if result.get("success") is not True:
        raise HTTPException(400, "Verification failed")

def smtp_available() -> bool:
    return all(os.getenv(x) for x in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"))

def send_mail(recipient: str, subject: str, body: str):
    if not smtp_available():
        raise RuntimeError("Email provider not configured")
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    host = os.environ["SMTP_HOST"]
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=10) as smtp:
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)

def notify_admin(inquiry_id: str, kind: str):
    address = os.getenv("ADMIN_NOTIFICATION_EMAIL", "")
    if not address or not smtp_available():
        return
    try:
        if kind == "financing request":
            subject = "Lending Ezy: New financing request"
            body = f"A new financing request was received. Sign in to the financing review desk and open reference {inquiry_id}."
        else:
            subject = f"Lending Ezy: New {kind} enquiry"
            body = f"A new enquiry was received. Sign in to the admin inbox to review reference {inquiry_id}."
        send_mail(address, subject, body)
    except Exception:
        logger.exception("Inquiry admin notification failed for %s", inquiry_id)

def summary(item: Inquiry):
    return {"id": item.id, "kind": item.kind, "name": item.name, "email": item.email,
            "country": item.country, "product_interest": item.product_interest,
            "institution": item.institution, "message": item.message, "status": item.status,
            "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}

@router.post("/inquiries", status_code=201)
def create_inquiry(data: InquiryInput, request: Request, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if os.getenv("PUBLIC_INQUIRIES_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Registration of interest is not yet open")
    verify_turnstile(data.turnstile_token, request)
    if data.website.strip(): # Return a generic acknowledgement without storing spam
        return {"received": True, "message": "Thank you for your interest."}
    email = str(data.email).strip().lower()
    window = datetime.now(timezone.utc) - timedelta(hours=24)
    count = db.scalar(select(func.count(Inquiry.id)).where(Inquiry.email == email, Inquiry.created_at >= window)) or 0
    if count >= 3:
        raise HTTPException(429, "Too many recent submissions. Please contact support.")
    item = Inquiry(kind=data.kind, name=data.name, email=email, country=data.country,
                   product_interest=data.product_interest if data.kind == "borrower" else None,
                   institution=data.institution.strip() if data.kind == "partner" and data.institution else None,
                   message=data.message.strip() if data.message else None,
                   consent_at=datetime.now(timezone.utc), status="new")
    db.add(item)
    db.commit()
    db.refresh(item)
    tasks.add_task(notify_admin, item.id, item.kind)
    return {"received": True, "reference": item.id, "message": "Your interest has been registered. This is not a credit application."}

@router.get("/admin/inquiries", dependencies=[Depends(require_admin)])
def list_inquiries(kind: Literal["borrower","partner"] | None = None,
                   status: Literal["new","in_progress","replied","closed"] | None = None,
                   limit: int = 60, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    statement = select(Inquiry)
    if kind:
        statement = statement.where(Inquiry.kind == kind)
    if status:
        statement = statement.where(Inquiry.status == status)
    items = db.scalars(statement.order_by(Inquiry.created_at.desc()).limit(limit)).all()
    return {"inquiries": [summary(x) for x in items]}

@router.get("/admin/inquiries/{inquiry_id}", dependencies=[Depends(require_admin)])
def read_inquiry(inquiry_id: str, db: Session = Depends(get_db)):
    item = db.get(Inquiry, inquiry_id)
    if item is None:
        raise HTTPException(404, "Enquiry not found")
    replies = db.scalars(select(InquiryReply).where(InquiryReply.inquiry_id == inquiry_id).order_by(InquiryReply.created_at.asc())).all()
    return {"inquiry": summary(item), "replies": [
        {"id": r.id, "body": r.body, "delivery_status": r.delivery_status, "created_at": r.created_at.isoformat(), "sent_at": r.sent_at.isoformat() if r.sent_at else None} for r in replies]}

@router.patch("/admin/inquiries/{inquiry_id}", dependencies=[Depends(require_admin)])
def change_status(inquiry_id: str, data: StatusUpdate, db: Session = Depends(get_db)):
    item = db.get(Inquiry, inquiry_id)
    if item is None:
        raise HTTPException(404, "Enquiry not found")
    item.status = data.status
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": item.status}

@router.post("/admin/inquiries/{inquiry_id}/reply", dependencies=[Depends(require_admin)], status_code=201)
def reply(inquiry_id: str, data: ReplyInput, db: Session = Depends(get_db)):
    item = db.get(Inquiry, inquiry_id)
    if item is None:
        raise HTTPException(404, "Enquiry not found")
    if data.action == "send" and not smtp_available():
        raise HTTPException(503, "Email sending is not configured. Save a draft instead.")
    record = InquiryReply(inquiry_id=item.id, body=data.body, delivery_status="draft")
    db.add(record)
    db.commit()
    db.refresh(record)
    if data.action == "send":
        try:
            send_mail(item.email, "Re: Your Lending Ezy enquiry", data.body)
        except Exception:
            logger.exception("Delivery failed for inquiry %s", item.id)
            raise HTTPException(502, "Email delivery failed. A draft was saved; do not assume delivery.")
        record.delivery_status = "sent" # SMTP accepted it; not proof of recipient inbox delivery.
        record.sent_at = datetime.now(timezone.utc)
        item.status = "replied"
        item.updated_at = datetime.now(timezone.utc)
        db.commit()
    return {"id": record.id, "delivery_status": record.delivery_status}
