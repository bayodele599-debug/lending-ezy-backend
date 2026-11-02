import os
from uuid import uuid4
os.environ["APP_ENV"] = "development"
os.environ["ENABLE_SANDBOX"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_sandbox.db"
os.environ["PUBLIC_INQUIRIES_ENABLED"] = "true"
os.environ["ADMIN_API_TOKEN"] = "test-secret-longer-than-thirty-two-characters"
from fastapi.testclient import TestClient
from app.main import app

HEADERS = {"X-Admin-Key": os.environ["ADMIN_API_TOKEN"]}
def payload():
    return {"kind": "partner", "name": "Test Contact", "email": f"test-{uuid4().hex}@example.test",
            "country": "GB", "institution": "Sample Credit Ltd", "message": "Testing demo intake",
            "consent_to_contact": True}

def test_submit_and_admin_inbox():
    with TestClient(app) as client:
        r = client.post("/api/v1/inquiries", json=payload())
        assert r.status_code == 201, r.text
        ref = r.json()["reference"]
        assert r.json()["received"] is True
        assert client.get("/api/v1/admin/inquiries").status_code == 401
        listing = client.get("/api/v1/admin/inquiries", headers=HEADERS)
        assert listing.status_code == 200
        assert any(x["id"] == ref for x in listing.json()["inquiries"])
        detail = client.get(f"/api/v1/admin/inquiries/{ref}", headers=HEADERS).json()
        assert detail["inquiry"]["institution"] == "Sample Credit Ltd"
        draft = client.post(f"/api/v1/admin/inquiries/{ref}/reply", headers=HEADERS,
                            json={"body": "Thank you for registering.", "action": "save_draft"})
        assert draft.status_code == 201
        assert draft.json()["delivery_status"] == "draft"
        no_smtp = client.post(f"/api/v1/admin/inquiries/{ref}/reply", headers=HEADERS,
                            json={"body": "Test email", "action": "send"})
        assert no_smtp.status_code == 503

def test_consent_required():
    with TestClient(app) as client:
        x = payload()
        x["consent_to_contact"] = False
        assert client.post("/api/v1/inquiries", json=x).status_code == 422
