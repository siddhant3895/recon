import pytest

from recon.normalizer import NormalizationError, normalize_record


def test_prefix_reference_and_amount_are_normalised():
    line = normalize_record(
        {
            "id": "S1",
            "text": "NEFT/12345678 Sharma Traders INVOICE 42",
            "amount": "Rs 1,234.50",
            "date": "05/10/2026",
            "direction": "debit",
        },
        "stmt",
    )
    assert line.amount_paise == 123450
    assert line.ref_token == "12345678"
    assert "12345678" not in line.text_norm
    assert "neft" not in line.text_norm
    assert line.direction == "debit"
    assert line.date_ambiguous is True


def test_ocr_numeric_repair_only_applies_to_ocr_rows():
    record = {
        "id": "S1",
        "text": "NEFT/1O23456789 Sharma Traders",
        "amount_paise": 100,
        "date": "2026-10-05",
        "direction": "credit",
    }
    csv_line = normalize_record({**record, "source": "csv"}, "stmt")
    ocr_line = normalize_record({**record, "source": "ocr"}, "stmt")
    assert csv_line.ref_token == "23456789"
    assert ocr_line.ref_token == "1023456789"
    assert "1023456789" not in ocr_line.text_norm


def test_date_ambiguity_rules():
    iso = normalize_record({"id": "1", "amount_paise": 1, "date": "2026-10-05", "direction": "debit"}, "stmt")
    clear = normalize_record({"id": "2", "amount_paise": 1, "date": "13/10/2026", "direction": "debit"}, "stmt")
    ambiguous = normalize_record({"id": "3", "amount_paise": 1, "date": "12/10/2026", "direction": "debit"}, "stmt")
    assert iso.date_ambiguous is False
    assert clear.date_ambiguous is False
    assert ambiguous.date_ambiguous is True


def test_negative_amount_infers_debit_and_keeps_absolute_value():
    line = normalize_record(
        {"id": "S1", "amount": "-500.25", "date": "2026-10-05"},
        "stmt",
    )
    assert line.amount_paise == 50025
    assert line.direction == "debit"


def test_missing_fields_raise_readable_errors():
    with pytest.raises(NormalizationError):
        normalize_record({"id": "S1", "date": "2026-10-05"}, "stmt")
    with pytest.raises(NormalizationError):
        normalize_record({"id": "S1", "amount_paise": 1}, "stmt")
    with pytest.raises(NormalizationError):
        normalize_record({"id": "S1", "amount_paise": 1, "date": "2026-10-05", "direction": "sideways"}, "stmt")


def test_unicode_narration_letters_are_preserved():
    line = normalize_record(
        {
            "id": "S1",
            "text": "UPI सूरज टेक्सटाइल भुगतान",
            "amount_paise": 100,
            "date": "2026-10-05",
            "direction": "debit",
        },
        "stmt",
    )
    assert "सूरज" in line.text_norm
    assert "टेक्सटाइल" in line.text_norm


def test_account_context_digits_are_not_treated_as_references():
    line = normalize_record(
        {
            "id": "S1",
            "text": "NEFT A/C 5023456789 REF 12345678 Sharma Traders",
            "amount_paise": 100,
            "date": "2026-10-05",
            "direction": "debit",
        },
        "stmt",
    )
    assert line.ref_token == "12345678"


def test_unmarked_digit_runs_stay_references():
    line = normalize_record(
        {
            "id": "S1",
            "text": "NEFT 5023456789 12345678 Sharma Traders",
            "amount_paise": 100,
            "date": "2026-10-05",
            "direction": "debit",
        },
        "stmt",
    )
    assert line.ref_token == "12345678 5023456789"


def test_dates_with_trailing_junk_are_rejected():
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount_paise": 1, "date": "2026-10-05junk", "direction": "debit"}, "stmt"
        )
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount_paise": 1, "date": "05/10/2026 12:00", "direction": "debit"}, "stmt"
        )


def test_sub_paise_amounts_are_rejected():
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount": "100.555", "date": "2026-10-05", "direction": "debit"}, "stmt"
        )


def test_zero_amounts_are_rejected():
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount_paise": 0, "date": "2026-10-05", "direction": "debit"}, "stmt"
        )
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount": "0.00", "date": "2026-10-05", "direction": "debit"}, "stmt"
        )


def test_direction_contradictions_are_rejected():
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount_paise": -100, "date": "2026-10-05", "direction": "credit"}, "stmt"
        )
    with pytest.raises(NormalizationError):
        normalize_record(
            {"id": "S1", "amount": "100 cr", "date": "2026-10-05", "direction": "debit"}, "stmt"
        )
    with pytest.raises(NormalizationError):
        normalize_record({"id": "S1", "amount": "(450) cr", "date": "2026-10-05"}, "stmt")


def test_positive_amount_without_direction_is_rejected():
    with pytest.raises(NormalizationError):
        normalize_record({"id": "S1", "amount_paise": 100, "date": "2026-10-05"}, "stmt")


def test_dr_cr_suffixes_still_infer_direction():
    debit = normalize_record({"id": "S1", "amount": "500 dr", "date": "2026-10-05"}, "stmt")
    credit = normalize_record({"id": "S2", "amount": "500 cr", "date": "2026-10-05"}, "stmt")
    assert debit.direction == "debit"
    assert credit.direction == "credit"
