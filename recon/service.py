from __future__ import annotations

import csv
import io
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .engine import run_matching
from .export import build_tables, compute_run_id, export_xlsx
from .golden import build_demo, build_golden
from .metrics import category_breakdown, evaluate, lines_from_golden

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

DEMO = build_demo(99)
DEMO_STMT, DEMO_LEDGER = lines_from_golden(DEMO)
DEMO_RESULT = run_matching(DEMO_STMT, DEMO_LEDGER)
DEMO_RUN_ID = compute_run_id(DEMO_RESULT)
DEMO_BY_ID = {line.id: line for line in DEMO_RESULT.lines}

ACCURACY = evaluate(build_golden(42))
ACCURACY["categories"] = {}

_lock = threading.Lock()
_decisions: list[dict] = []
_audit: list[dict] = []
_leads: list[dict] = []
_next_id = 1

app = FastAPI(title="Recon", version="1.0")


class DecisionIn(BaseModel):
    stmt_line_id: str
    ledger_line_ids: list[str] = Field(default_factory=list)
    action: Literal["accept", "reject", "unmatch", "undo"]
    reason: str | None = None
    candidate_key: str | None = None
    target_decision_id: int | None = None


class LeadIn(BaseModel):
    name: str
    firm: str
    email: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_audit(verb: str, actor: str, obj: str, meta: dict) -> None:
    _audit.append({"id": len(_audit) + 1, "at": _now(), "verb": verb, "actor": actor, "object": obj, "meta": meta})


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "normalizer_version": DEMO_RESULT.normalizer_version}


@app.get("/api/accuracy")
def accuracy() -> dict:
    return ACCURACY


@app.get("/api/demo")
def demo() -> dict:
    candidates_by_stmt: dict[str, list] = {}
    for candidate in DEMO_RESULT.candidates:
        candidates_by_stmt.setdefault(candidate.stmt_line_id, []).append(candidate)

    state_order = {"auto_suggest": 0, "review": 1, "unmatched": 2}
    statement_rows = []
    for line in DEMO_STMT:
        rows = sorted(
            candidates_by_stmt.get(line.id, []),
            key=lambda candidate: (-candidate.score, tuple(candidate.ledger_line_ids)),
        )
        statement_rows.append(
            {
                **line.to_dict(),
                "candidates": [candidate.to_dict() for candidate in rows],
            }
        )
    statement_rows.sort(key=lambda row: (state_order.get(row["match_state"], 3), row["id"]))

    ledger_rows = [
        {
            **line.to_dict(),
            "referenced": any(line.id in candidate.ledger_line_ids for candidate in DEMO_RESULT.candidates),
        }
        for line in DEMO_LEDGER
    ]
    ledger_rows.sort(key=lambda row: row["id"])

    tier4 = [candidate for candidate in DEMO_RESULT.candidates if candidate.tier == 4]
    tier4_example = max(tier4, key=lambda candidate: (candidate.score, candidate.stmt_line_id), default=None)

    with _lock:
        decisions = list(_decisions)

    return {
        "watermark": DEMO.get("watermark", "SAMPLE DATA"),
        "run_id": DEMO_RUN_ID,
        "normalizer_version": DEMO_RESULT.normalizer_version,
        "counts": DEMO_RESULT.counts,
        "tiers": {str(k): v for k, v in DEMO_RESULT.tiers.items()},
        "statement": statement_rows,
        "ledger": ledger_rows,
        "decisions": decisions,
        "tier4_example": tier4_example.to_dict() if tier4_example else None,
    }


@app.post("/api/demo/decisions")
def decide(payload: DecisionIn) -> dict:
    global _next_id
    if payload.stmt_line_id not in DEMO_BY_ID:
        raise HTTPException(status_code=404, detail="statement line not found")

    candidate_keys = {
        (
            candidate.stmt_line_id,
            tuple(sorted(candidate.ledger_line_ids)),
        )
        for candidate in DEMO_RESULT.candidates
    }
    key = (payload.stmt_line_id, tuple(sorted(payload.ledger_line_ids)))
    if payload.action in {"accept", "reject"} and key not in candidate_keys:
        raise HTTPException(status_code=422, detail="candidate not in this run")
    if payload.action == "reject" and payload.reason not in {
        "wrong amount",
        "wrong party",
        "wrong period",
        "duplicate",
        "other",
    }:
        raise HTTPException(status_code=422, detail="reject requires a listed reason")
    if payload.action == "undo":
        with _lock:
            if payload.target_decision_id is None or not any(
                row["id"] == payload.target_decision_id for row in _decisions
            ):
                raise HTTPException(status_code=404, detail="decision to undo not found")

    with _lock:
        row = {
            "id": _next_id,
            "stmt_line_id": payload.stmt_line_id,
            "ledger_line_ids": list(payload.ledger_line_ids),
            "action": payload.action,
            "reason": payload.reason,
            "candidate_key": payload.candidate_key,
            "target_decision_id": payload.target_decision_id,
            "decided_at": _now(),
        }
        _next_id += 1
        _decisions.append(row)
        _append_audit("decision", "reviewer", f"stmt:{payload.stmt_line_id}", row)
    return row


@app.post("/api/demo/reset")
def reset() -> dict:
    with _lock:
        _decisions.clear()
        _audit.clear()
    return {"ok": True}


@app.get("/api/demo/audit")
def audit() -> dict:
    with _lock:
        return {"append_only": True, "events": list(_audit)}


@app.get("/api/export/xlsx")
def export_workbook() -> Response:
    with _lock:
        decisions = [dict(row) for row in _decisions]
    buffer = io.BytesIO()
    export_xlsx(DEMO_RESULT, buffer, decisions=decisions)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="recon-{DEMO_RUN_ID}.xlsx"'},
    )


@app.get("/api/export/csv")
def export_csv_zip() -> Response:
    with _lock:
        decisions = [dict(row) for row in _decisions]
    tables = build_tables(DEMO_RESULT, decisions=decisions)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, rows in tables.items():
            member = io.StringIO()
            writer = csv.writer(member)
            writer.writerows(rows)
            archive.writestr(f"{name}.csv", member.getvalue())
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="recon-{DEMO_RUN_ID}.zip"'},
    )


@app.post("/api/shadow-month")
def shadow_month(payload: LeadIn) -> dict:
    if not payload.name.strip() or not payload.firm.strip() or "@" not in payload.email:
        raise HTTPException(status_code=422, detail="name, firm and a valid email are required")
    with _lock:
        entry = {
            "id": len(_leads) + 1,
            "name": payload.name.strip(),
            "firm": payload.firm.strip(),
            "email": payload.email.strip(),
            "at": _now(),
        }
        _leads.append(entry)
        _append_audit("shadow_month_request", "visitor", f"lead:{entry['id']}", {"firm": entry["firm"]})
    return {"ok": True, "id": entry["id"], "message": "Received. We will reply within one working day."}


def _page(name: str) -> FileResponse:
    path = WEB_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(path)


@app.get("/")
def home():
    return _page("index.html")


@app.get("/how-it-works")
def how_it_works():
    return _page("how-it-works.html")


@app.get("/accuracy")
def accuracy_page():
    return _page("accuracy.html")


@app.get("/security")
def security_page():
    return _page("security.html")


@app.get("/pricing")
def pricing_page():
    return _page("pricing.html")


@app.get("/demo")
def demo_page():
    return _page("demo.html")


@app.get("/shadow-month")
def shadow_month_page():
    return _page("shadow-month.html")


@app.get("/about")
def about_page():
    return _page("about.html")


@app.get("/legal/{doc}")
def legal_page(doc: str):
    if doc not in {"terms", "privacy", "dpa"}:
        raise HTTPException(status_code=404, detail="not found")
    return _page(f"legal/{doc}.html")


@app.get("/static/{name:path}")
def static_file(name: str):
    path = WEB_DIR / "static" / name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
