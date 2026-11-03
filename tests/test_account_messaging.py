"""Customer financing request visibility, messaging, and ownership boundaries."""
import os
from uuid import uuid4
from fastapi.testclient import TestClient

os.environ["CUSTOMER_ACCOUNTS_ENABLED"] = "true"
os.environ["PUBLIC_FINANCING_REQUESTS_ENABLED"] = "true"
from app.main import app
from app import accounts

ADMIN = {"X-Admin-Key": "test-secret-longer-than-thirty-two-characters"}


def customer(client, monkeypatch):
    links = []
    monkeypatch.setattr(accounts, "send_token", lambda customer, kind, token: links.append(token))
    email = "portal-%s@example.com" % uuid4().hex
    password = "Long test passphrase 2026!"
    new = client.post("/api/v1/account/register", json={
        "full_name": "Customer Portal Test", "email": email,
        "country": "GB", "password": password, "consent_to_terms": True})
    assert new.status_code == 201, new.text
    assert client.post("/api/v1/account/verify-email", json={"token": links[-1]}).status_code == 200
    signed = client.post("/api/v1/account/login", json={"email":email, "password":password})
    assert signed.status_code == 200, signed.text
    return email, {"Authorization": "Bearer "+signed.json()["token"]}


def test_customer_submission_thread_does_not_leak_private_notes(monkeypatch):
    with TestClient(app) as client:
        first_email, first = customer(client, monkeypatch)
        second_email, second = customer(client, monkeypatch)
        data = {
            "client_token":str(uuid4()),"kind":"personal","purpose":"Education",
            "country":"GB","currency":"GBP","amount":"15000",
            "term_months":24,"assumed_annual_rate":"9",
            "name":"Customer Portal Test","email":first_email,
            "consent_to_contact":True,"confirms_estimate_only":True
        }
        assert client.post("/api/v1/financing-requests",json={
            **data,"email":second_email},headers=first).status_code == 403
        created = client.post("/api/v1/financing-requests",json=data,headers=first)
        assert created.status_code == 201,created.text
        ref = created.json()["reference"]
        assert any(x["id"]==ref for x in client.get("/api/v1/account/requests",headers=first).json()["requests"])
        assert client.get("/api/v1/account/requests",headers=second).json()["requests"] == []
        assert client.get("/api/v1/account/requests").status_code == 401
        assert client.get("/api/v1/account/requests/"+ref+"/messages",headers=second).status_code == 404
        assert client.post("/api/v1/account/requests/"+ref+"/messages",json={
            "body":"An attempt to see another person's messages"},headers=second).status_code == 404
        assert client.get("/api/v1/admin/financing-requests/"+ref+"/messages").status_code == 401
        review = client.patch("/api/v1/admin/financing-requests/"+ref,headers=ADMIN,
            json={"status":"needs_information","expected_status":"submitted",
                  "note":"INTERNAL ONLY: identity review checklist, not for applicant"})
        assert review.status_code == 200,review.text
        sent = client.post("/api/v1/admin/financing-requests/"+ref+"/messages",
                           headers=ADMIN,json={"body":"Could you clarify your study duration?"})
        assert sent.status_code == 201,sent.text
        replied = client.post("/api/v1/account/requests/"+ref+"/messages",headers=first,
                             json={"body":"The course runs for two academic years."})
        assert replied.status_code == 201,replied.text
        thread = client.get("/api/v1/account/requests/"+ref+"/messages",headers=first)
        assert thread.status_code == 200
        assert len(thread.json()["messages"]) == 2
        assert thread.json()["messages"][0]["author"] == "admin"
        assert thread.json()["messages"][1]["author"] == "customer"
        assert "INTERNAL ONLY" not in str(thread.json())
        export = client.get("/api/v1/account/export",headers=first)
        assert export.status_code == 200
        assert "INTERNAL ONLY" not in export.text
        assert ref in export.text
        metrics = client.get("/api/v1/admin/financing-metrics",headers=ADMIN)
        assert metrics.status_code == 200 and metrics.json()["total"] >= 1
        assert metrics.json()["attention"] >= 1
        assert client.get("/api/v1/admin/financing-metrics").status_code == 401
        assert "INTERNAL ONLY" in str(client.get(
            "/api/v1/admin/financing-requests/"+ref,headers=ADMIN).json())
        assert client.get("/api/v1/admin/financing-requests/"+ref+"/messages",
            headers=ADMIN).json()["has_customer_account"] is True


def test_anonymous_requests_cannot_be_taken_over_by_matching_email(monkeypatch):
    with TestClient(app) as client:
        email, headers = customer(client, monkeypatch)
        anonymous = client.post("/api/v1/financing-requests", json={
            "client_token":str(uuid4()),"kind":"personal","purpose":"Education",
            "country":"GB","currency":"GBP","amount":"10000",
            "term_months":24,"assumed_annual_rate":"8",
            "name":"Anonymous Visitor", "email":email,
            "consent_to_contact":True,"confirms_estimate_only":True
        })
        assert anonymous.status_code == 201,anonymous.text
        ref = anonymous.json()["reference"]
        assert ref not in [x["id"] for x in client.get("/api/v1/account/requests",headers=headers).json()["requests"]]
        assert client.get("/api/v1/account/requests/"+ref+"/messages",headers=headers).status_code == 404
        assert client.post("/api/v1/admin/financing-requests/"+ref+"/messages",headers=ADMIN,
            json={"body":"A message should not be delivered to an unlinked portal"}).status_code == 409
