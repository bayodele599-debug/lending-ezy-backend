import os
os.environ["APP_ENV"] = "development"
os.environ["ENABLE_SANDBOX"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_sandbox.db"
from fastapi.testclient import TestClient
from app.main import app

def test_quote_and_markets():
    with TestClient(app) as client:
        markets = client.get("/api/v1/markets")
        assert markets.status_code == 200
        assert markets.json()["live_lending_markets"] == []
        response = client.post("/api/v1/quote", json={"product_id": "flex", "currency": "USD", "principal": "10000.00", "term_months": 12})
        assert response.status_code == 200
        assert response.json()["schedule"][-1]["balance"] == "0.00"

def test_demo_application():
    with TestClient(app) as client:
        response = client.post("/api/v1/sandbox/applications", json={"product_id": "flex", "currency": "USD", "principal": "3000.00", "term_months": 12})
        assert response.status_code == 201
        row = client.get("/api/v1/sandbox/applications/" + response.json()["id"])
        assert row.status_code == 200
        assert row.json()["status"] == "sandbox_submitted"
