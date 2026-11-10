from __future__ import annotations

from collections import Counter

from .cascade import TIER4_NODE_CAP, Cascade
from .models import Candidate, Line, RunResult
from .normalizer import NORMALIZER_VERSION


def run_matching(
    stmt_lines: list[Line],
    ledger_lines: list[Line],
    node_cap: int = TIER4_NODE_CAP,
) -> RunResult:
    cascade = Cascade(stmt_lines, ledger_lines, node_cap=node_cap)
    by_stmt = cascade.run()

    candidates: list[Candidate] = []
    states: Counter[str] = Counter()
    for stmt in cascade.stmt_lines:
        rows = by_stmt.get(stmt.id, [])
        candidates.extend(rows)
        if rows:
            stmt.match_state = rows[0].band
        else:
            stmt.match_state = "unmatched"
        states[stmt.match_state] += 1

    tier_counts = Counter(candidate.tier for candidate in candidates)
    counts = {
        "statement_lines": len(cascade.stmt_lines),
        "ledger_lines": len(cascade.ledger_lines),
        "candidates": len(candidates),
        "auto_suggest": states["auto_suggest"],
        "review": states["review"],
        "unmatched": states["unmatched"],
        "tier4_abandoned": cascade.tier4_abandoned,
        "tier4_nodes": cascade.tier4_nodes,
    }

    return RunResult(
        normalizer_version=NORMALIZER_VERSION,
        candidates=candidates,
        lines=list(cascade.stmt_lines) + list(cascade.ledger_lines),
        counts=counts,
        tiers={tier: tier_counts.get(tier, 0) for tier in (1, 2, 3, 4)},
    )
