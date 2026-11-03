"""Real HTTP / PostgreSQL smoke test for a local development stack.
Creates one synthetic example visible in the admin review desk.
"""
import os
import uuid
import sys
import httpx

API = os.getenv("LOCAL_API_URL", "http://127.0.0.1:8000")
SECRET = os.getenv("ADMIN_API_TOKEN", "")
if len(SECRET) < 32 or os.getenv("APP_ENV") != "development":
    raise SystemExit("Refusing to run the local smoke test without development mode and a test admin token")

key = str(uuid.uuid4())
payload = {
    "client_token": key,
    "kind": "business",
    "purpose": "Working capital",
    "country": "GB",
    "currency": "GBP",
    "amount": "45000.00",
    "term_months": 36,
    "assumed_annual_rate": "8.00",
    "name": "Lending Ezy Local Test",
    "email": f"test-{uuid.uuid4().hex}@example.com",
    "business_name": "Local Demonstration Ltd",
    "message": "Synthetic integration test; no real borrower",
    "consent_to_contact": True,
    "confirms_estimate_only": True,
}
headers = {"X-Admin-Key": SECRET}
with httpx.Client(base_url=API, timeout=15) as c:
    health = c.get("/health")
    assert health.status_code == 200, health.text
    unauth = c.get("/api/v1/admin/financing-requests")
    assert unauth.status_code == 401, unauth.text
    sent = c.post("/api/v1/financing-requests", json=payload)
    assert sent.status_code == 201, sent.text
    ref = sent.json()["reference"]
    assert sent.json()["status"] == "submitted" and ref
    duplicate = c.post("/api/v1/financing-requests", json=payload)
    assert duplicate.status_code == 201 and duplicate.json()["reference"] == ref, duplicate.text
    listed = c.get("/api/v1/admin/financing-requests?kind=business", headers=headers)
    assert listed.status_code == 200 and any(x["id"] == ref for x in listed.json()["requests"]), listed.text
    detail = c.get(f"/api/v1/admin/financing-requests/{ref}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["request"]["amount"] == "45000.00"
    assert len(detail.json()["history"]) == 1
    updated = c.patch(f"/api/v1/admin/financing-requests/{ref}", headers=headers, json={
        "status": "in_review", "expected_status": "submitted", "note": "Manual local integration review"
    })
    assert updated.status_code == 200 and updated.json()["status"] == "in_review", updated.text
    trail = c.get(f"/api/v1/admin/financing-requests/{ref}", headers=headers).json()["history"]
    assert len(trail) == 2 and trail[-1]["note"] == "Manual local integration review", trail
    print(f"PASS: PostgreSQL-backed intake -> idempotency -> protected admin -> review history. Reference: {ref}")
    print("A synthetic record is available for inspection in the admin Requests queue.")
