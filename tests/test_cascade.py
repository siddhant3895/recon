from datetime import date, timedelta

from recon.engine import run_matching
from recon.normalizer import normalize_record
from recon.scoring import gate_failures


def make_line(line_id, side, amount, day, direction, text, source="csv"):
    return normalize_record(
        {
            "id": line_id,
            "text": text,
            "amount_paise": amount,
            "date": day.isoformat(),
            "direction": direction,
            "source": source,
        },
        side,
    )


def run_one(stmt, *ledgers):
    result = run_matching([stmt], list(ledgers))
    return result, result.candidates_for(stmt.id)


def test_tier1_exact_reference_and_same_date():
    day = date(2026, 10, 8)
    stmt = make_line("S1", "stmt", 500_000, day, "debit", "NEFT/12345678 Sharma Traders INVOICE 1")
    led = make_line("L1", "ledger", 500_000, day, "debit", "NEFT 12345678 Sharma Traders INV 1")
    result, candidates = run_one(stmt, led)
    assert len(candidates) == 1
    assert candidates[0].tier == 1
    assert candidates[0].score == 100
    assert candidates[0].band == "auto_suggest"
    assert gate_failures(stmt, [led], 1) == []
    assert result.counts["auto_suggest"] == 1


def test_tier2_fuzzy_reference_within_three_days():
    day = date(2026, 10, 8)
    stmt = make_line("S1", "stmt", 500_000, day, "debit", "RTGS 12345678 Sharma Traders INVOICE 1")
    led = make_line("L1", "ledger", 500_000, day + timedelta(days=2), "debit", "RTGS 12345679 Sharma Traders INV 1")
    _, candidates = run_one(stmt, led)
    assert candidates[0].tier == 2
    assert 60 <= candidates[0].score < 100


def test_tier3_amount_band_and_narration():
    day = date(2026, 10, 8)
    stmt = make_line("S1", "stmt", 500_000, day, "credit", "UPI Sharma Traders INVOICE 1001 SETTLEMENT")
    led = make_line(
        "L1",
        "ledger",
        501_500,
        day + timedelta(days=5),
        "credit",
        "UPI Sharma Traders INV 1001 SETTLEMENT RECEIVED",
    )
    _, candidates = run_one(stmt, led)
    assert candidates[0].tier == 3
    assert candidates[0].band in {"review", "auto_suggest"}


def test_tier4_finds_the_two_line_split():
    day = date(2026, 10, 8)
    stmt = make_line("S1", "stmt", 1_000_000, day, "debit", "IMPS BATCH Sharma Traders INVOICE 1001")
    led_one = make_line("L1", "ledger", 370_000, day, "debit", "Sharma Traders INVOICE 1001 PART 1")
    led_two = make_line("L2", "ledger", 630_000, day + timedelta(days=1), "debit", "Sharma Traders INVOICE 1001 PART 2")
    _, candidates = run_one(stmt, led_one, led_two)
    assert candidates[0].tier == 4
    assert candidates[0].ledger_line_ids == ["L1", "L2"]
    assert candidates[0].comp["delta_amount_paise"] == 0


def test_direction_gate_discards_everything():
    day = date(2026, 10, 8)
    stmt = make_line("S1", "stmt", 500_000, day, "debit", "NEFT/12345678 Sharma Traders")
    led = make_line("L1", "ledger", 500_000, day, "credit", "NEFT 12345678 Sharma Traders")
    _, candidates = run_one(stmt, led)
    assert candidates == []


def test_tier4_node_cap_abandons_instead_of_hanging():
    day = date(2026, 10, 8)
    stmt = make_line("S1", "stmt", 1_000_000, day, "debit", "IMPS BATCH Unknown Party")
    ledgers = [
        make_line(f"L{i}", "ledger", 1_000 + i, day, "debit", f"Other Party invoice {i}")
        for i in range(50)
    ]
    result = run_matching([stmt], ledgers, node_cap=1)
    assert result.candidates_for(stmt.id) == []
    assert result.counts["tier4_abandoned"] == 1
