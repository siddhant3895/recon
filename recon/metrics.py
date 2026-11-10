from __future__ import annotations

from collections import Counter
from typing import Any

from .engine import run_matching
from .models import Line
from .normalizer import normalize_record
from .scoring import gate_failures


def evaluate(golden: dict[str, Any], node_cap: int | None = None) -> dict[str, Any]:
    stmt_lines, ledger_lines = lines_from_golden(golden)
    result = run_matching(stmt_lines, ledger_lines, **({"node_cap": node_cap} if node_cap else {}))
    labels = {key: frozenset(value) for key, value in golden["labels"].items()}
    ledger_by_id = {line.id: line for line in ledger_lines}
    stmt_by_id = {line.id: line for line in stmt_lines}

    best = result.best_by_stmt
    by_stmt: dict[str, list] = {}
    for candidate in result.candidates:
        by_stmt.setdefault(candidate.stmt_line_id, []).append(candidate)

    auto_total = 0
    auto_correct = 0
    wrong_auto: list[dict[str, Any]] = []
    recall_hits = 0
    recall_top_hits = 0
    missing: list[str] = []

    for stmt_id, truth in sorted(labels.items()):
        candidates = by_stmt.get(stmt_id, [])
        top = best.get(stmt_id)

        if top is not None and top.score >= 95:
            auto_total += 1
            if frozenset(top.ledger_line_ids) == truth:
                auto_correct += 1
            else:
                wrong_auto.append(
                    {
                        "stmt_line_id": stmt_id,
                        "expected": sorted(truth),
                        "got": list(top.ledger_line_ids),
                        "score": top.score,
                        "reason": top.reason,
                    }
                )

        surfaced = False
        for candidate in candidates:
            if candidate.score >= 60 and frozenset(candidate.ledger_line_ids) == truth:
                surfaced = True
                break
        if surfaced:
            recall_hits += 1
        else:
            missing.append(stmt_id)

        if top is not None and top.score >= 60 and frozenset(top.ledger_line_ids) == truth:
            recall_top_hits += 1

    gate_violations: list[dict[str, Any]] = []
    for candidate in result.candidates:
        ledgers: list[Line] = [ledger_by_id[line_id] for line_id in candidate.ledger_line_ids]
        failures = gate_failures(stmt_by_id[candidate.stmt_line_id], ledgers, candidate.tier)
        if failures:
            gate_violations.append(
                {
                    "stmt_line_id": candidate.stmt_line_id,
                    "ledger_line_ids": list(candidate.ledger_line_ids),
                    "tier": candidate.tier,
                    "failures": failures,
                }
            )

    total = len(labels)
    precision_auto = (auto_correct / auto_total) if auto_total else 1.0
    recall = (recall_hits / total) if total else 1.0
    recall_top = (recall_top_hits / total) if total else 1.0

    return {
        "normalizer_version": result.normalizer_version,
        "dataset": {
            "statement_lines": len(stmt_lines),
            "ledger_lines": len(ledger_lines),
            "labelled_pairs": total,
            "auto_suggest_lines": auto_total,
            "gate_violations": len(gate_violations),
        },
        "metrics": {
            "precision_auto_suggest": round(precision_auto, 4),
            "recall_overall": round(recall, 4),
            "recall_top1": round(recall_top, 4),
            "auto_suggest_rate": round(auto_total / total, 4) if total else 0.0,
            "review_rate": round(result.counts["review"] / total, 4) if total else 0.0,
            "unmatched_rate": round(result.counts["unmatched"] / total, 4) if total else 0.0,
        },
        "counts": result.counts,
        "tiers": {str(key): value for key, value in result.tiers.items()},
        "wrong_auto_suggests": wrong_auto,
        "missing_pairs": missing,
        "gate_violations": gate_violations,
    }


def lines_from_golden(golden: dict[str, Any]) -> tuple[list[Line], list[Line]]:
    stmt_lines = [normalize_record(record, "stmt") for record in golden["statement"]]
    ledger_lines = [normalize_record(record, "ledger") for record in golden["ledger"]]
    return stmt_lines, ledger_lines


def category_breakdown(golden: dict[str, Any]) -> dict[str, int]:
    return dict(sorted(Counter(golden.get("categories", {}).values()).items()))
