import pytest
from fastapi.testclient import TestClient
from recon.service import app

@pytest.fixture(scope="module")
def client():
    return TestClient(app)

def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["ok"] is True

def test_web_pages_load(client):
    pages = [
        "/",
        "/how-it-works",
        "/accuracy",
        "/security",
        "/pricing",
        "/demo",
        "/shadow-month",
        "/about",
        "/legal/terms",
        "/legal/privacy",
        "/legal/dpa",
    ]
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Page {page} returned {res.status_code}"
        assert len(res.text) > 200

def test_demo_api(client):
    res = client.get("/api/demo")
    assert res.status_code == 200
    data = res.json()
    assert "statement" in data
    assert "ledger" in data
    assert len(data["statement"]) > 0

def test_shadow_month_lead_submission(client):
    res = client.post("/api/shadow-month", json={
        "name": "CA Test Lead",
        "firm": "Lead & Co, Nagpur",
        "email": "test@lead-ca.in"
    })
    assert res.status_code == 200
    assert res.json()["ok"] is True
