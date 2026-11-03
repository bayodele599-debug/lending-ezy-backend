"""Intake and admin review contract for financing requests."""
import os
from uuid import uuid4

os.environ["APP_ENV"] = "development"
os.environ["ENABLE_SANDBOX"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_sandbox.db"
os.environ["PUBLIC_FINANCING_REQUESTS_ENABLED"] = "true"
os.environ["ADMIN_API_TOKEN"] = "test-secret-longer-than-thirty-two-characters"

from fastapi.testclient import TestClient
from app.main import app

ADMIN = {"X-Admin-Key": os.environ["ADMIN_API_TOKEN"]}


def new_payload(**overrides):
    data = {
        "client_token": str(uuid4()),
        "kind": "business", "purpose": "Working capital", "country": "GB",
        "currency": "GBP", "amount": "45000.00", "term_months": 36,
        "assumed_annual_rate": "12.00", "name": "Research Borrower",
        "email": f"request-{uuid4().hex}@example.com", "business_name": "Example Ltd",
        "message": "Exploring a financing request.", "consent_to_contact": True,
        "confirms_estimate_only": True
    }
    data.update(overrides)
    return data


def test_submission_listing_detail_and_review():
    with TestClient(app) as client:
        data = new_payload()
        response = client.post("/api/v1/financing-requests", json=data)
        assert response.status_code == 201, response.text
        reference = response.json()["reference"]
        assert response.json()["status"] == "submitted"

        assert client.get("/api/v1/admin/financing-requests").status_code == 401
        assert client.get(f"/api/v1/admin/financing-requests/{reference}").status_code == 401
        assert client.patch(f"/api/v1/admin/financing-requests/{reference}", json={
            "status": "in_review", "expected_status": "submitted", "note": "Review started"
        }).status_code == 401

        listed = client.get("/api/v1/admin/financing-requests?kind=business&status=submitted", headers=ADMIN)
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] >= 1
        assert any(x["id"] == reference for x in listed.json()["requests"])
        detail = client.get(f"/api/v1/admin/financing-requests/{reference}", headers=ADMIN).json()
        assert detail["request"]["email"] == data["email"]
        assert detail["request"]["amount"] == "45000.00"
        assert detail["request"]["estimate"]["monthly_payment"]
        assert len(detail["history"]) == 1
        assert detail["history"][0]["actor"] == "customer"

        changed = client.patch(f"/api/v1/admin/financing-requests/{reference}", headers=ADMIN, json={
            "status": "in_review", "expected_status": "submitted", "note": "Reviewing details"
        })
        assert changed.status_code == 200, changed.text
        assert changed.json()["status"] == "in_review"
        stale = client.patch(f"/api/v1/admin/financing-requests/{reference}", headers=ADMIN, json={
            "status": "not_proceeding", "expected_status": "submitted", "note": "Stale operator"
        })
        assert stale.status_code == 409
        invalid = client.patch(f"/api/v1/admin/financing-requests/{reference}", headers=ADMIN, json={
            "status": "submitted", "expected_status": "in_review", "note": "Not allowed"
        })
        assert invalid.status_code == 422
        shortlisted = client.patch(f"/api/v1/admin/financing-requests/{reference}", headers=ADMIN, json={
            "status": "proceed_to_next_stage", "expected_status": "in_review",
            "note": "Proceed with manual lender follow-up"
        })
        assert shortlisted.status_code == 200
        history = client.get(f"/api/v1/admin/financing-requests/{reference}", headers=ADMIN).json()["history"]
        assert len(history) == 3
        assert history[-1]["note"] == "Proceed with manual lender follow-up"
        assert history[-1]["actor"] == "admin"


def test_idempotency_and_anti_tampering():
    with TestClient(app) as client:
        data = new_payload()
        r1 = client.post("/api/v1/financing-requests", json=data)
        r2 = client.post("/api/v1/financing-requests", json=data)
        assert r1.status_code == 201
        assert r1.json()["reference"] == r2.json()["reference"]
        assert client.post("/api/v1/financing-requests", json={**data, "amount": "10000.00"}).status_code == 409


def test_input_validation_and_intake_off(monkeypatch):
    with TestClient(app) as client:
        for change in [
            {"consent_to_contact": False}, {"confirms_estimate_only": False},
            {"currency": "XYZ"}, {"amount": "-500"}, {"term_months": 13},
            {"assumed_annual_rate": "90.00"}, {"country": "WORLD"},
            {"kind": "business", "business_name": ""},
        ]:
            assert client.post("/api/v1/financing-requests", json=new_payload(**change)).status_code == 422
        monkeypatch.setenv("PUBLIC_FINANCING_REQUESTS_ENABLED", "false")
        assert client.post("/api/v1/financing-requests", json=new_payload()).status_code == 503


def test_rate_limit_and_no_public_details():
    with TestClient(app) as client:
        email = f"repeat-{uuid4().hex}@example.com"
        ids = []
        for _ in range(3):
            r = client.post("/api/v1/financing-requests", json=new_payload(email=email))
            assert r.status_code == 201
            ids.append(r.json()["reference"])
        assert client.post("/api/v1/financing-requests", json=new_payload(email=email)).status_code == 429
        assert client.get(f"/api/v1/financing-requests/{ids[0]}").status_code == 404
