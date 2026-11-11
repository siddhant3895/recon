import csv
import io
import zipfile

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


def _read_zip_tables(res):
    archive = zipfile.ZipFile(io.BytesIO(res.content))
    tables = {}
    for name in archive.namelist():
        rows = list(csv.reader(io.StringIO(archive.read(name).decode("utf-8"))))
        tables[name[:-len(".csv")]] = rows
    return tables


def test_export_csv_endpoint_returns_zip(client):
    res = client.get("/api/export/csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/zip")
    tables = _read_zip_tables(res)
    assert set(tables) == {
        "matched_pairs",
        "proposed_unreviewed",
        "unmatched",
        "unparsed",
        "decisions",
        "summary",
    }
    assert tables["matched_pairs"][0][0] == "stmt_line_id"
    assert tables["unmatched"][0][0] == "line_id"


def test_export_xlsx_endpoint_returns_workbook(client):
    res = client.get("/api/export/xlsx")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(res.content) > 0


def test_exports_honour_decisions(client):
    client.post("/api/demo/reset")

    demo = client.get("/api/demo").json()
    with_candidates = [row for row in demo["statement"] if row["candidates"]]
    assert len(with_candidates) >= 2
    first, second = with_candidates[0], with_candidates[1]

    accepted = client.post("/api/demo/decisions", json={
        "stmt_line_id": first["id"],
        "ledger_line_ids": first["candidates"][0]["ledger_line_ids"],
        "action": "accept",
    })
    assert accepted.status_code == 200

    rejected = client.post("/api/demo/decisions", json={
        "stmt_line_id": second["id"],
        "ledger_line_ids": second["candidates"][0]["ledger_line_ids"],
        "action": "reject",
        "reason": "wrong party",
    })
    assert rejected.status_code == 200

    tables = _read_zip_tables(client.get("/api/export/csv"))
    matched_ids = {row[0] for row in tables["matched_pairs"][1:]}
    proposed_ids = {row[0] for row in tables["proposed_unreviewed"][1:]}
    unmatched_states = {row[0]: row[6] for row in tables["unmatched"][1:]}
    assert matched_ids == {first["id"]}
    assert first["id"] not in proposed_ids
    assert second["id"] not in proposed_ids
    assert unmatched_states[second["id"]] == "rejected: wrong party"

    undo = client.post("/api/demo/decisions", json={
        "stmt_line_id": first["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": accepted.json()["id"],
    })
    assert undo.status_code == 200

    tables = _read_zip_tables(client.get("/api/export/csv"))
    matched_ids = {row[0] for row in tables["matched_pairs"][1:]}
    proposed_ids = {row[0] for row in tables["proposed_unreviewed"][1:]}
    assert first["id"] not in matched_ids
    assert first["id"] in proposed_ids

    client.post("/api/demo/reset")
