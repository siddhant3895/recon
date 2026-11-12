import csv
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor

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
    assert "working day" not in res.json()["message"].lower()


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


def test_decision_invariants_and_undo_validation(client):
    client.post("/api/demo/reset")

    demo = client.get("/api/demo").json()
    row = next(r for r in demo["statement"] if r["candidates"])
    payload = {
        "stmt_line_id": row["id"],
        "ledger_line_ids": row["candidates"][0]["ledger_line_ids"],
        "action": "accept",
    }

    accepted = client.post("/api/demo/decisions", json=payload)
    assert accepted.status_code == 200
    decision_id = accepted.json()["id"]

    duplicate = client.post("/api/demo/decisions", json=payload)
    assert duplicate.status_code == 409

    missing_target = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": 999999,
    })
    assert missing_target.status_code == 404

    undo = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": decision_id,
    })
    assert undo.status_code == 200

    undo_again = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": decision_id,
    })
    assert undo_again.status_code == 409

    reaccepted = client.post("/api/demo/decisions", json=payload)
    assert reaccepted.status_code == 200

    other = next(r for r in demo["statement"] if r["candidates"] and r["id"] != row["id"])
    wrong_stmt = client.post("/api/demo/decisions", json={
        "stmt_line_id": other["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": reaccepted.json()["id"],
    })
    assert wrong_stmt.status_code == 409

    client.post("/api/demo/reset")


def test_reject_validation_and_undo_of_undo(client):
    client.post("/api/demo/reset")
    demo = client.get("/api/demo").json()
    row = next(r for r in demo["statement"] if r["candidates"])
    ledger_ids = row["candidates"][0]["ledger_line_ids"]

    bad_reason = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": ledger_ids,
        "action": "reject",
        "reason": "because",
    })
    assert bad_reason.status_code == 422

    rejected = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": ledger_ids,
        "action": "reject",
        "reason": "wrong amount",
    })
    assert rejected.status_code == 200
    decision_id = rejected.json()["id"]

    events = client.get("/api/demo/audit").json()["events"]
    decision_events = [e for e in events if e["verb"] == "decision" and e["object"] == f"stmt:{row['id']}"]
    assert decision_events[-1]["meta"]["reason"] == "wrong amount"

    undo = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": decision_id,
    })
    assert undo.status_code == 200
    undo_id = undo.json()["id"]

    undo_undo = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": undo_id,
    })
    assert undo_undo.status_code == 422

    client.post("/api/demo/reset")


def test_ledger_line_cannot_be_allocated_to_two_statements(client):
    client.post("/api/demo/reset")
    demo = client.get("/api/demo").json()

    owners = {}
    for row in demo["statement"]:
        for candidate in row["candidates"]:
            for ledger_id in candidate["ledger_line_ids"]:
                owners.setdefault(ledger_id, []).append((row["id"], candidate["ledger_line_ids"]))
    competing = [
        (ledger_id, pairs)
        for ledger_id, pairs in owners.items()
        if len({stmt_id for stmt_id, _ in pairs}) >= 2
    ]
    assert competing, "demo data is expected to contain a ledger line proposed for two statements"

    ledger_id, pairs = competing[0]
    first_stmt, first_ledger = pairs[0]
    second_stmt, second_ledger = next(pair for pair in pairs if pair[0] != first_stmt)

    first = client.post("/api/demo/decisions", json={
        "stmt_line_id": first_stmt,
        "ledger_line_ids": first_ledger,
        "action": "accept",
    })
    assert first.status_code == 200

    second = client.post("/api/demo/decisions", json={
        "stmt_line_id": second_stmt,
        "ledger_line_ids": second_ledger,
        "action": "accept",
    })
    assert second.status_code == 409
    assert ledger_id in second.json()["detail"]

    undo = client.post("/api/demo/decisions", json={
        "stmt_line_id": first_stmt,
        "ledger_line_ids": [],
        "action": "undo",
        "target_decision_id": first.json()["id"],
    })
    assert undo.status_code == 200

    retried = client.post("/api/demo/decisions", json={
        "stmt_line_id": second_stmt,
        "ledger_line_ids": second_ledger,
        "action": "accept",
    })
    assert retried.status_code == 200

    client.post("/api/demo/reset")


def test_concurrent_duplicate_decides_produce_one_winner(client):
    client.post("/api/demo/reset")
    demo = client.get("/api/demo").json()
    row = next(r for r in demo["statement"] if r["candidates"])
    payload = {
        "stmt_line_id": row["id"],
        "ledger_line_ids": row["candidates"][0]["ledger_line_ids"],
        "action": "accept",
    }
    events_before = client.get("/api/demo/audit").json()["events"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: client.post("/api/demo/decisions", json=payload), range(4))
        )
    assert sorted(res.status_code for res in responses) == [200, 409, 409, 409]

    events_after = client.get("/api/demo/audit").json()["events"]
    new_events = events_after[len(events_before):]
    assert len(new_events) == 1
    assert new_events[0]["verb"] == "decision"
    assert new_events[0]["meta"]["action"] == "accept"

    client.post("/api/demo/reset")


def test_static_route_serves_files_but_rejects_traversal(client):
    good = client.get("/static/css/style.css")
    assert good.status_code == 200

    traversal_urls = [
        "/static/%2e%2e/recon/service.py",
        "/static/..%2frecon/service.py",
        "/static/%2e%2e%2f%2e%2e/recon/engine.py",
        "/static/css/%2e%2e/%2e%2e/recon/service.py",
    ]
    for url in traversal_urls:
        res = client.get(url)
        assert res.status_code == 404, f"{url} returned {res.status_code}"


def test_reset_clears_decisions_but_keeps_the_audit_append_only(client):
    client.post("/api/demo/reset")
    demo = client.get("/api/demo").json()
    row = next(r for r in demo["statement"] if r["candidates"])
    accepted = client.post("/api/demo/decisions", json={
        "stmt_line_id": row["id"],
        "ledger_line_ids": row["candidates"][0]["ledger_line_ids"],
        "action": "accept",
    })
    assert accepted.status_code == 200

    events_before = client.get("/api/demo/audit").json()["events"]
    assert len(events_before) >= 1

    reset = client.post("/api/demo/reset")
    assert reset.status_code == 200
    assert reset.json()["cleared_decisions"] == 1

    events_after = client.get("/api/demo/audit").json()["events"]
    assert len(events_after) == len(events_before) + 1
    assert events_after[-1]["verb"] == "reset"
    assert events_after[-1]["meta"]["cleared_decisions"] == 1

    demo_after = client.get("/api/demo").json()
    assert demo_after["decisions"] == []
