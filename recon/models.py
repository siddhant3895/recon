from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

Direction = Literal["debit", "credit"]
Side = Literal["stmt", "ledger"]
Band = Literal["auto_suggest", "review", "unmatched"]


@dataclass
class Line:
    id: str
    side: Side
    amount_paise: int
    direction: Direction
    date: date
    date_ambiguous: bool
    ref_token: str
    text_norm: str
    source: str = "csv"
    raw: dict[str, Any] = field(default_factory=dict)
    match_state: Band = "unmatched"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "side": self.side,
            "amount_paise": self.amount_paise,
            "direction": self.direction,
            "date_iso": self.date.isoformat(),
            "date_ambiguous": self.date_ambiguous,
            "ref_token": self.ref_token,
            "text_norm": self.text_norm,
            "source": self.source,
            "match_state": self.match_state,
            "raw": self.raw,
        }


@dataclass
class Candidate:
    stmt_line_id: str
    ledger_line_ids: list[str]
    score: int
    comp: dict[str, Any]
    reason: str
    tier: int

    @property
    def band(self) -> Band:
        if self.score >= 95:
            return "auto_suggest"
        if self.score >= 60:
            return "review"
        return "unmatched"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stmt_line_id": self.stmt_line_id,
            "ledger_line_ids": list(self.ledger_line_ids),
            "score": self.score,
            "comp": self.comp,
            "reason": self.reason,
            "tier": self.tier,
            "band": self.band,
        }


@dataclass
class RunResult:
    normalizer_version: str
    candidates: list[Candidate]
    lines: list[Line]
    counts: dict[str, Any]
    tiers: dict[int, int] = field(default_factory=dict)

    @property
    def best_by_stmt(self) -> dict[str, Candidate]:
        best: dict[str, Candidate] = {}
        for candidate in self.candidates:
            current = best.get(candidate.stmt_line_id)
            if current is None or _candidate_order(candidate) < _candidate_order(current):
                best[candidate.stmt_line_id] = candidate
        return best

    def candidates_for(self, stmt_line_id: str) -> list[Candidate]:
        rows = [c for c in self.candidates if c.stmt_line_id == stmt_line_id]
        return sorted(rows, key=_candidate_order)

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalizer_version": self.normalizer_version,
            "counts": self.counts,
            "tiers": {str(k): v for k, v in sorted(self.tiers.items())},
            "candidates": [c.to_dict() for c in sorted(self.candidates, key=_candidate_order)],
            "lines": [line.to_dict() for line in sorted(self.lines, key=lambda item: (item.side, item.id))],
        }


def _candidate_order(candidate: Candidate) -> tuple[int, tuple[str, ...], int]:
    return (-candidate.score, tuple(candidate.ledger_line_ids), candidate.tier)
