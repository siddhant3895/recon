from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .models import RunResult


def compute_run_id(result: RunResult) -> str:
    payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _resolve_decisions(decisions: Iterable[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    rows = list(decisions or [])
    undone_ids = {
        row.get("target_decision_id")
        for row in rows
        if row.get("action") == "undo" and row.get("target_decision_id") is not None
    }
    active: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("action") == "undo":
            continue
        if row.get("id") is not None and row["id"] in undone_ids:
            continue
        active[row["stmt_line_id"]] = row
    return active


def build_tables(
    result: RunResult,
    decisions: Iterable[dict[str, Any]] | None = None,
    unparsed: Iterable[dict[str, Any]] | None = None,
    run_id: str | None = None,
) -> dict[str, list[list[Any]]]:
    run_id = run_id or compute_run_id(result)
    line_by_id = {line.id: line for line in result.lines}
    active_decisions = _resolve_decisions(decisions)
    accepted_keys = {
        (row["stmt_line_id"], tuple(sorted(row.get("ledger_line_ids", []))))
        for row in active_decisions.values()
        if row.get("action") == "accept"
    }
    accepted_ledger = {
        ledger_id
        for row in active_decisions.values()
        if row.get("action") == "accept"
        for ledger_id in row.get("ledger_line_ids", [])
    }
    proposed_ledger = {ledger_id for candidate in result.candidates for ledger_id in candidate.ledger_line_ids}

    pair_header: list[Any] = [
        "stmt_line_id",
        "ledger_line_ids",
        "score",
        "band",
        "tier",
        "reason",
        "stmt_amount_paise",
        "ledger_amount_paise",
        "stmt_date",
        "ledger_dates",
        "stmt_text",
        "ledger_text",
    ]
    matched: list[list[Any]] = [pair_header]
    proposed: list[list[Any]] = [pair_header]
    for candidate in sorted(result.candidates, key=lambda c: (-c.score, c.stmt_line_id)):
        stmt = line_by_id[candidate.stmt_line_id]
        ledger_lines = [line_by_id[ledger_id] for ledger_id in candidate.ledger_line_ids]
        row: list[Any] = [
            stmt.id,
            " | ".join(candidate.ledger_line_ids),
            candidate.score,
            candidate.band,
            candidate.tier,
            candidate.reason,
            stmt.amount_paise,
            sum(line.amount_paise for line in ledger_lines),
            stmt.date.isoformat(),
            " | ".join(line.date.isoformat() for line in ledger_lines),
            stmt.text_norm,
            " | ".join(line.text_norm for line in ledger_lines),
        ]
        key = (candidate.stmt_line_id, tuple(sorted(candidate.ledger_line_ids)))
        if key in accepted_keys:
            matched.append(row)
        elif candidate.stmt_line_id not in active_decisions:
            proposed.append(row)

    candidate_by_key = {
        (candidate.stmt_line_id, tuple(sorted(candidate.ledger_line_ids))): candidate
        for candidate in result.candidates
    }
    unmatched: list[list[Any]] = [["line_id", "side", "amount_paise", "date", "direction", "text", "state"]]
    for line in sorted(result.lines, key=lambda item: (item.side, item.id)):
        if line.side == "stmt":
            decision = active_decisions.get(line.id)
            if decision is None:
                if line.match_state == "unmatched":
                    unmatched.append(_line_row(line, "unmatched"))
            elif decision.get("action") == "reject":
                unmatched.append(_line_row(line, f"rejected: {decision.get('reason') or 'unspecified'}"))
            elif decision.get("action") == "unmatch":
                unmatched.append(_line_row(line, "unmatched by reviewer"))
            elif decision.get("action") == "accept":
                key = (line.id, tuple(sorted(decision.get("ledger_line_ids", []))))
                if key not in candidate_by_key:
                    unmatched.append(_line_row(line, "accepted pair missing from run"))
        elif line.side == "ledger":
            if line.id not in accepted_ledger:
                state = "proposed, not accepted" if line.id in proposed_ledger else "unmatched"
                unmatched.append(_line_row(line, state))

    unparsed_rows: list[list[Any]] = [["line_id", "side", "reason", "raw"]]
    for row in unparsed or []:
        unparsed_rows.append([
            row.get("id", ""),
            row.get("side", ""),
            row.get("reason", ""),
            json.dumps(row.get("raw", {}), sort_keys=True),
        ])

    decision_rows: list[list[Any]] = [["candidate_key", "stmt_line_id", "ledger_line_ids", "action", "reason", "decided_at"]]
    for row in decisions or []:
        decision_rows.append([
            row.get("candidate_key", ""),
            row.get("stmt_line_id", ""),
            " | ".join(row.get("ledger_line_ids", [])),
            row.get("action", ""),
            row.get("reason", ""),
            row.get("decided_at", ""),
        ])

    summary: list[list[Any]] = [["metric", "value"]]
    summary.append(["run_id", run_id])
    summary.append(["normalizer_version", result.normalizer_version])
    for key, value in sorted(result.counts.items()):
        summary.append([key, value])
    for tier, count in sorted(result.tiers.items()):
        summary.append([f"tier_{tier}_candidates", count])
    summary.append(["unparsed_rows", len(unparsed_rows) - 1])
    summary.append(["accepted_pairs", len(matched) - 1])
    summary.append(["proposed_unreviewed_candidates", len(proposed) - 1])
    summary.append(["unmatched_rows", len(unmatched) - 1])

    return {
        "matched_pairs": matched,
        "proposed_unreviewed": proposed,
        "unmatched": unmatched,
        "unparsed": unparsed_rows,
        "decisions": decision_rows,
        "summary": summary,
    }


def export_csv(
    result: RunResult,
    out_dir: str | Path,
    decisions: Iterable[dict[str, Any]] | None = None,
    unparsed: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    tables = build_tables(result, decisions, unparsed)
    paths: dict[str, Path] = {}
    for name, rows in tables.items():
        path = directory / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
        paths[name] = path
    return paths


def export_xlsx(
    result: RunResult,
    path: str | Path | Any,
    decisions: Iterable[dict[str, Any]] | None = None,
    unparsed: Iterable[dict[str, Any]] | None = None,
) -> Any:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for XLSX export") from exc

    tables = build_tables(result, decisions, unparsed)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in tables.items():
        sheet = workbook.create_sheet(title=name[:31])
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        if rows:
            sheet.auto_filter.ref = sheet.dimensions

    if hasattr(path, "write"):
        workbook.save(path)
        return path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    return target


def _line_row(line, state: str | None = None) -> list[Any]:
    return [
        line.id,
        line.side,
        line.amount_paise,
        line.date.isoformat(),
        line.direction,
        line.text_norm,
        state if state is not None else line.match_state,
    ]
