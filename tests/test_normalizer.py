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
