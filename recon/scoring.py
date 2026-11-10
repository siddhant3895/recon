from __future__ import annotations

import math

from .models import Candidate, Line
from .similarity import ref_similarity, token_set_ratio

TIER_DATE_WINDOW = {1: 0, 2: 3, 3: 30, 4: 10}
AMBIGUOUS_DATE_WINDOW = 30


def amount_band_paise(stmt_amount: int, tier: int) -> int:
    if tier in (1, 2):
        return 0
    if tier == 3:
        return int(round(0.02 * stmt_amount))
    return max(100, int(round(0.005 * stmt_amount)))


def date_window_days(tier: int, stmt: Line, ledgers: list[Line]) -> int:
    if stmt.date_ambiguous or any(line.date_ambiguous for line in ledgers):
        return AMBIGUOUS_DATE_WINDOW
    return TIER_DATE_WINDOW[tier]


def amount_delta(stmt: Line, ledgers: list[Line]) -> int:
    return abs(stmt.amount_paise - sum(line.amount_paise for line in ledgers))


def date_delta(stmt: Line, ledgers: list[Line]) -> int:
    return max(abs((line.date - stmt.date).days) for line in ledgers)


def gate_failures(stmt: Line, ledgers: list[Line], tier: int) -> list[str]:
    failures: list[str] = []
    if any(line.direction != stmt.direction for line in ledgers):
        failures.append("direction")
    delta_amount = amount_delta(stmt, ledgers)
    band = amount_band_paise(stmt.amount_paise, tier)
    if delta_amount > band:
        failures.append("amount")
    delta_date = date_delta(stmt, ledgers)
    window = date_window_days(tier, stmt, ledgers)
    if delta_date > window:
        failures.append("date")
    return failures


def score_candidate(stmt: Line, ledgers: list[Line], tier: int) -> Candidate:
    delta_amount = amount_delta(stmt, ledgers)
    amount_score = _amount_component(stmt.amount_paise, delta_amount, tier)

    delta_date = date_delta(stmt, ledgers)
    window = date_window_days(tier, stmt, ledgers)
    date_score = _date_component(delta_date, window)

    ledger_ref = " ".join(line.ref_token for line in ledgers if line.ref_token)
    ref_sim = ref_similarity(stmt.ref_token, ledger_ref) if stmt.ref_token and ledger_ref else 0.0
    ref_score = 20.0 * ref_sim

    ledger_text = " ".join(line.text_norm for line in ledgers)
    narration = token_set_ratio(stmt.text_norm, ledger_text)
    narration_score = 10.0 * narration

    total = int(math.floor(amount_score + date_score + ref_score + narration_score + 0.5))
    total = max(0, min(100, total))

    comp = {
        "amount": round(amount_score, 3),
        "date": round(date_score, 3),
        "reference": round(ref_score, 3),
        "narration": round(narration_score, 3),
        "ref_similarity": round(ref_sim, 4),
        "narration_ratio": round(narration, 4),
        "delta_amount_paise": delta_amount,
        "delta_date_days": delta_date,
        "date_window_days": window,
    }

    return Candidate(
        stmt_line_id=stmt.id,
        ledger_line_ids=[line.id for line in ledgers],
        score=total,
        comp=comp,
        reason=_reason(stmt, ledgers, tier, delta_amount, delta_date, ref_sim, narration),
        tier=tier,
    )


def _amount_component(stmt_amount: int, delta: int, tier: int) -> float:
    band = amount_band_paise(stmt_amount, tier)
    if delta == 0:
        return 45.0
    if band <= 0 or delta >= band:
        return 0.0
    return 45.0 * (1.0 - delta / band)


def _date_component(delta: int, window: int) -> float:
    if delta == 0:
        return 25.0
    if window <= 0 or delta >= window:
        return 0.0
    return 25.0 * (1.0 - delta / window)


def _reason(
    stmt: Line,
    ledgers: list[Line],
    tier: int,
    delta_amount: int,
    delta_date: int,
    ref_sim: float,
    narration: float,
) -> str:
    parts: list[str] = []
    if tier == 4:
        parts.append(f"split across {len(ledgers)} ledger lines")
    if delta_amount == 0:
        parts.append("exact amount")
    else:
        parts.append(f"amount off by Rs {delta_amount / 100:,.2f}")
    if delta_date == 0:
        parts.append("same day")
    else:
        parts.append(f"{delta_date} day{'s' if delta_date != 1 else ''} apart")
    if not stmt.ref_token or not any(line.ref_token for line in ledgers):
        parts.append("no reference")
    elif ref_sim >= 0.999:
        parts.append("reference matches")
    elif ref_sim >= 0.85:
        parts.append(f"reference close ({ref_sim:.2f})")
    else:
        parts.append(f"reference differs ({ref_sim:.2f})")
    parts.append(f"narration {narration:.2f}")
    return ", ".join(parts)
