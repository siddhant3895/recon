import json
from datetime import date, timedelta

import pytest

from recon.engine import run_matching
from recon.export import compute_run_id, export_csv, export_xlsx
from recon.golden import build_golden
from recon.metrics import evaluate, lines_from_golden
from recon.normalizer import normalize_record


@pytest.fixture(scope="session")
def golden():
    return build_golden(seed=42)


def test_golden_accuracy_meets_targets(golden):
    report = evaluate(golden)
    assert report["metrics"]["precision_auto_suggest"] >= 0.97
    assert report["metrics"]["recall_overall"] >= 0.85
    assert report["dataset"]["gate_violations"] == 0


def test_determinism_across_100_repeat_runs(golden):
    stmt_lines, ledger_lines = lines_from_golden(golden)
    baseline = None
    for _ in range(100):
        result = run_matching(stmt_lines, ledger_lines)
        serialised = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
        if baseline is None:
            baseline = serialised
        else:
            assert serialised == baseline
    assert baseline is not None


def test_5000_row_statement_completes_under_90_seconds():
    import time

    rows = 5000
    stmt_lines = []
    ledger_lines = []
    base = date(2026, 9, 1)
    for index in range(rows):
        amount = 100_000 + index * 1_009
        day = base + timedelta(days=index % 28)
        ref = str(20_000_000 + index * 31)
        direction = "debit" if index % 2 else "credit"
        stmt_lines.append(
            normalize_record(
                {
                    "id": f"S{index:05d}",
                    "text": f"NEFT/{ref} Bench Vendor {index}",
                    "amount_paise": amount,
                    "date": day.isoformat(),
                    "direction": direction,
                },
                "stmt",
            )
        )
        ledger_lines.append(
            normalize_record(
                {
                    "id": f"L{index:05d}",
                    "text": f"NEFT {ref} Bench Vendor {index}",
                    "amount_paise": amount,
                    "date": (day + timedelta(days=index % 3)).isoformat(),
                    "direction": direction,
                },
                "ledger",
            )
        )
    started = time.perf_counter()
    result = run_matching(stmt_lines, ledger_lines)
    elapsed = time.perf_counter() - started
    assert elapsed < 90.0
    assert result.counts["statement_lines"] == rows


def test_unparsed_rows_appear_in_export(golden, tmp_path):
    stmt_lines, ledger_lines = lines_from_golden(golden)
    stmt_lines = stmt_lines[:3]
    result = run_matching(stmt_lines, ledger_lines)
    unparsed = [{"id": "SX", "side": "stmt", "reason": "missing amount", "raw": {"id": "SX"}}]
    paths = export_csv(result, tmp_path, unparsed=unparsed)
    text = paths["unparsed"].read_text(encoding="utf-8")
    assert "missing amount" in text
    assert "SX" in text


def test_exports_include_all_required_sheets(golden, tmp_path):
    stmt_lines, ledger_lines = lines_from_golden(golden)
    result = run_matching(stmt_lines[:10], ledger_lines)
    csv_paths = export_csv(result, tmp_path)
    expected_sheets = {
        "matched_pairs",
        "proposed_unreviewed",
        "unmatched",
        "unparsed",
        "decisions",
        "summary",
    }
    assert set(csv_paths) == expected_sheets
    xlsx_path = export_xlsx(result, tmp_path / "export.xlsx")
    from openpyxl import load_workbook

    workbook = load_workbook(xlsx_path, read_only=True)
    assert set(workbook.sheetnames) == expected_sheets
    workbook.close()


def test_run_id_is_stable(golden):
    stmt_lines, ledger_lines = lines_from_golden(golden)
    first = compute_run_id(run_matching(stmt_lines, ledger_lines))
    second = compute_run_id(run_matching(stmt_lines, ledger_lines))
    assert first == second


def test_purge_job_removes_raw_objects_and_writes_audit_row(tmp_path):
    from recon.purge import purge_expired_uploads

    storage = tmp_path / "storage"
    storage.mkdir()
    file1 = storage / "upload_1.csv"
    file1.write_text("dummy bank statement data", encoding="utf-8")
    file2 = storage / "upload_2.csv"
    file2.write_text("active bank statement data", encoding="utf-8")

    records = [
        {
            "id": "U1",
            "firm_id": "F100",
            "storage_key": "upload_1.csv",
            "purge_after": "2026-10-01T00:00:00Z",
            "purged": False,
        },
        {
            "id": "U2",
            "firm_id": "F100",
            "storage_key": "upload_2.csv",
            "purge_after": "2026-12-01T00:00:00Z",
            "purged": False,
        },
    ]

    purged, updated, audits = purge_expired_uploads(
        records, storage, cutoff_iso="2026-11-01T00:00:00Z"
    )

    assert purged == 1
    assert not file1.exists()
    assert file2.exists()
    assert updated[0]["purged"] is True
    assert updated[0]["storage_key"] is None
    assert updated[1]["purged"] is False
    assert len(audits) == 1
    assert audits[0]["verb"] == "purge"
    assert audits[0]["actor"] == "retention_worker"
    assert audits[0]["object"] == "upload:U1"

