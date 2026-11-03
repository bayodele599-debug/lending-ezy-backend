"""Isolated account auth and persisted plan contracts.

External email is mocked. Real PostgreSQL migrations + HTTP tests run separately.
"""
import os
from uuid import uuid4
from fastapi.testclient import TestClient

os.environ["CUSTOMER_ACCOUNTS_ENABLED"] = "true"
from app.main import app
from app import accounts


def register_verified(client, monkeypatch):
    captures = []
    monkeypatch.setattr(accounts, "send_token", lambda user, kind, token: captures.append((kind, token)))
    email = "account-%s@example.com" % uuid4().hex
    password = "A long test passphrase 2026!"
    result = client.post("/api/v1/account/register", json={
        "email": email, "password": password, "full_name": "Local Account Test",
        "country": "GB", "consent_to_terms": True})
    assert result.status_code == 201, result.text
    assert captures and captures[-1][0] == "verify"
    assert client.post("/api/v1/account/login",json={"email":email,"password":password}).status_code == 403
    verification = client.post("/api/v1/account/verify-email", json={"token":captures[-1][1]})
    assert verification.status_code == 200, verification.text
    assert client.post("/api/v1/account/verify-email", json={"token":captures[-1][1]}).status_code == 400
    login = client.post("/api/v1/account/login",json={"email":email,"password":password})
    assert login.status_code == 200,login.text
    return email,password,{"Authorization":"Bearer "+login.json()["token"]},captures


def test_accounts_password_reset_sessions_and_tenant_isolation(monkeypatch):
    with TestClient(app) as c:
        email,password,auth,captures = register_verified(c,monkeypatch)
        other_email,other_password,other_auth,second_captures = register_verified(c,monkeypatch)
        assert c.get("/api/v1/account/me").status_code == 401
        own = c.get("/api/v1/account/me",headers=auth)
        assert own.status_code == 200 and own.json()["email"] == email
        assert c.get("/api/v1/account/me",headers=other_auth).json()["email"] == other_email

        new = c.post("/api/v1/account/plans",headers=auth,json={
            "type":"personal","purpose":"Education","country":"GB","currency":"GBP",
            "amount":"12000.00","months":24,"annual_rate":"12.00"})
        assert new.status_code == 201,new.text
        plan_id = new.json()["id"]
        assert len(c.get("/api/v1/account/plans",headers=auth).json()["plans"]) == 1
        assert c.get("/api/v1/account/plans",headers=other_auth).json()["plans"] == []
        assert c.patch("/api/v1/account/plans/"+plan_id,headers=other_auth,json={
            "type":"business","purpose":"Equipment","country":"GB","currency":"GBP",
            "amount":35000,"months":36,"annual_rate":9}).status_code == 404
        assert c.delete("/api/v1/account/plans/"+plan_id,headers=other_auth).status_code == 404

        updated = c.patch("/api/v1/account/plans/"+plan_id,headers=auth,json={
            "type":"personal","purpose":"Education","country":"GB","currency":"GBP",
            "amount":"14000","months":36,"annual_rate":"8.5"})
        assert updated.status_code == 200 and updated.json()["amount"] == "14000.00",updated.text

        assert c.post("/api/v1/account/password/request-reset",json={"email":email}).status_code == 200
        reset = second_captures[-1]
        assert reset[0] == "reset"
        assert c.post("/api/v1/account/password/reset",json={
            "token":reset[1],"password":"A brand new secure passphrase!"}).status_code == 200
        assert c.get("/api/v1/account/me",headers=auth).status_code == 401
        assert c.post("/api/v1/account/login",json={"email":email,"password":password}).status_code == 401
        fresh = c.post("/api/v1/account/login",json={
            "email":email,"password":"A brand new secure passphrase!"})
        assert fresh.status_code == 200
        fresh_auth = {"Authorization":"Bearer "+fresh.json()["token"]}
        assert c.delete("/api/v1/account/plans/"+plan_id,headers=fresh_auth).status_code == 200
        assert c.get("/api/v1/account/plans",headers=fresh_auth).json()["plans"] == []
        assert c.post("/api/v1/account/logout",headers=fresh_auth).status_code == 200
        assert c.get("/api/v1/account/me",headers=fresh_auth).status_code == 401


def test_public_access_remains_disabled_by_default(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setenv("CUSTOMER_ACCOUNTS_ENABLED","false")
        assert c.get("/api/v1/account/me").status_code == 503
        assert c.post("/api/v1/account/register",json={
            "email":"test@example.com","password":"Some very long passphrase!",
            "full_name":"Test Account","country":"GB","consent_to_terms":True}).status_code == 503
