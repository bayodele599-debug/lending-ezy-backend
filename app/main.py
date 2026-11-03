"""Lending Ezy API: financing request intake, admin review, and isolated sandbox quotes."""
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .config import APP_ENV, ENABLE_SANDBOX, CORS_ORIGINS
from .db import Base, engine, get_db
from .finance import amortize
from .models import DemoApplication

PRODUCTS = {
 "flex": {"id": "flex", "name": "Flex personal", "description": "Illustrative personal loan", "min": 500, "max": 50000, "rate_bps": 1250, "terms": [6, 12, 24, 36]},
 "growth": {"id": "growth", "name": "Growth business", "description": "Illustrative business capital", "min": 5000, "max": 250000, "rate_bps": 1090, "terms": [12, 24, 36, 60]},
 "advance": {"id": "advance", "name": "Salary advance", "description": "Illustrative short-term credit", "min": 250, "max": 10000, "rate_bps": 990, "terms": [3, 6, 12]}
}
CURRENCIES = ["USD", "GBP", "EUR", "CAD", "AUD", "SGD"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    if APP_ENV == "development":
        Base.metadata.create_all(bind=engine)  # Only for local development. Deploy migrations before production.
    yield

app = FastAPI(title="Lending Ezy API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "X-Admin-Key", "Authorization"])
from .inquiries import router as inquiry_router
app.include_router(inquiry_router)
from .requests import router as financing_router
app.include_router(financing_router)
from .accounts import router as account_router
app.include_router(account_router)

class QuoteRequest(BaseModel):
    product_id: str
    currency: str = "USD"
    principal: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    term_months: int = Field(ge=1, le=360)

def valid_product(data: QuoteRequest) -> dict:
    product = PRODUCTS.get(data.product_id)
    if product is None:
        raise HTTPException(422, "Unknown product")
    if data.currency not in CURRENCIES:
        raise HTTPException(422, "Currency unavailable for illustrations")
    if not (Decimal(product["min"]) <= data.principal <= Decimal(product["max"])):
        raise HTTPException(422, "Principal outside product limits")
    if data.term_months not in product["terms"]:
        raise HTTPException(422, "Unsupported product term")
    return product

def sandbox_guard():
    if not ENABLE_SANDBOX or APP_ENV != "development":
        raise HTTPException(404, "Sandbox endpoints disabled")

@app.get("/health")
def health():
    return {"status": "ok", "mode": "sandbox" if APP_ENV == "development" and ENABLE_SANDBOX else "restricted"}

@app.get("/api/v1/markets")
def markets():
    return {"availability": "public_information_only", "live_lending_markets": [], "currencies_for_illustration": CURRENCIES}

@app.get("/api/v1/products")
def products():
    return {"products": list(PRODUCTS.values()), "status": "illustration_only"}

@app.post("/api/v1/quote")
def quote(data: QuoteRequest):
    product = valid_product(data)
    return {"product_id": data.product_id, "currency": data.currency, "principal": str(data.principal), "nominal_annual_rate_bps": product["rate_bps"], "term_months": data.term_months, "illustrative": True, **amortize(data.principal, product["rate_bps"], data.term_months)}

@app.post("/api/v1/sandbox/applications", dependencies=[Depends(sandbox_guard)], status_code=201)
def submit_demo(data: QuoteRequest, db: Annotated[Session, Depends(get_db)]):
    product = valid_product(data)
    row = DemoApplication(product_id=data.product_id, currency=data.currency, principal=data.principal, annual_rate_bps=product["rate_bps"], term_months=data.term_months)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status, "message": "Test record only. No real loan application or decision was made."}

@app.get("/api/v1/sandbox/applications/{app_id}", dependencies=[Depends(sandbox_guard)])
def demo_detail(app_id: str, db: Annotated[Session, Depends(get_db)]):
    row = db.get(DemoApplication, app_id)
    if row is None:
        raise HTTPException(404, "Sandbox application not found")
    return {"id": row.id, "product_id": row.product_id, "currency": row.currency, "principal": str(row.principal), "term_months": row.term_months, "status": row.status, "created_at": row.created_at}

@app.get("/api/v1/sandbox/partner-overview", dependencies=[Depends(sandbox_guard)])
def demo_partner(db: Annotated[Session, Depends(get_db)]):
    return {"mode": "sandbox", "application_count": db.query(DemoApplication).count(), "live_originations": 0, "live_disbursements": 0, "live_repayments": 0}
