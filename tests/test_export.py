import pytest

from recon.engine import run_matching
from recon.export import build_tables
from recon.golden import build_golden
from recon.metrics import lines_from_golden


@pytest.fixture(scope="module")
def run():
    golden = build_golden(seed=42)
    stmt_lines, ledger_lines = lines_from_golden(golden)
    return run_matching(stmt_lines[:20], ledger_lines)


def _matched_stmt_ids(tables):
    return {row[0] for row in tables["matched_pairs"][1:]}


def _proposed_stmt_ids(tables):
    return {row[0] for row in tables["proposed_unreviewed"][1:]}


def _unmatched_rows(tables):
    return {row[0]: row[6] for row in tables["unmatched"][1:]}


def _first_candidate(run):
    for candidate in sorted(run.candidates, key=lambda c: c.stmt_line_id):
        return candidate
    raise AssertionError("golden run has no candidates")


def test_no_decisions_keeps_every_candidate_proposed(run):
    tables = build_tables(run)
    assert _matched_stmt_ids(tables) == set()
    assert _proposed_stmt_ids(tables) == {c.stmt_line_id for c in run.candidates}


def test_accepted_decision_moves_candidate_to_matched(run):
    candidate = _first_candidate(run)
    decisions = [{"id": 1, "stmt_line_id": candidate.stmt_line_id, "ledger_line_ids": list(candidate.ledger_line_ids), "action": "accept"}]
    tables = build_tables(run, decisions=decisions)
    matched = _matched_stmt_ids(tables)
    assert matched == {candidate.stmt_line_id}
    assert candidate.stmt_line_id not in _proposed_stmt_ids(tables)
    unmatched = _unmatched_rows(tables)
    assert candidate.stmt_line_id not in unmatched
    for ledger_id in candidate.ledger_line_ids:
        assert ledger_id not in unmatched


def test_rejected_decision_marks_stmt_unmatched_with_reason(run):
    candidate = _first_candidate(run)
    decisions = [
        {
            "id": 1,
            "stmt_line_id": candidate.stmt_line_id,
            "ledger_line_ids": list(candidate.ledger_line_ids),
            "action": "reject",
            "reason": "wrong party",
        }
    ]
    tables = build_tables(run, decisions=decisions)
    assert _matched_stmt_ids(tables) == set()
    assert candidate.stmt_line_id not in _proposed_stmt_ids(tables)
    assert _unmatched_rows(tables)[candidate.stmt_line_id] == "rejected: wrong party"


def test_unmatch_decision_marks_stmt_unmatched_by_reviewer(run):
    candidate = _first_candidate(run)
    decisions = [{"id": 1, "stmt_line_id": candidate.stmt_line_id, "ledger_line_ids": [], "action": "unmatch"}]
    tables = build_tables(run, decisions=decisions)
    assert _matched_stmt_ids(tables) == set()
    assert candidate.stmt_line_id not in _proposed_stmt_ids(tables)
    assert _unmatched_rows(tables)[candidate.stmt_line_id] == "unmatched by reviewer"


def test_undo_suppresses_the_targeted_decision(run):
    candidate = _first_candidate(run)
    decisions = [
        {
            "id": 7,
            "stmt_line_id": candidate.stmt_line_id,
            "ledger_line_ids": list(candidate.ledger_line_ids),
            "action": "accept",
        },
        {"id": 8, "stmt_line_id": candidate.stmt_line_id, "action": "undo", "target_decision_id": 7},
    ]
    tables = build_tables(run, decisions=decisions)
    assert _matched_stmt_ids(tables) == set()
    assert candidate.stmt_line_id in _proposed_stmt_ids(tables)


def test_newer_decision_supersedes_older_one(run):
    candidate = _first_candidate(run)
    decisions = [
        {
            "id": 1,
            "stmt_line_id": candidate.stmt_line_id,
            "ledger_line_ids": list(candidate.ledger_line_ids),
            "action": "accept",
        },
        {"id": 2, "stmt_line_id": candidate.stmt_line_id, "ledger_line_ids": [], "action": "unmatch"},
    ]
    tables = build_tables(run, decisions=decisions)
    assert _matched_stmt_ids(tables) == set()
    assert candidate.stmt_line_id not in _proposed_stmt_ids(tables)
    assert _unmatched_rows(tables)[candidate.stmt_line_id] == "unmatched by reviewer"


def test_accept_for_missing_candidate_is_flagged(run):
    stmt_id = next(line.id for line in run.lines if line.side == "stmt")
    decisions = [
        {"id": 1, "stmt_line_id": stmt_id, "ledger_line_ids": ["L-DOES-NOT-EXIST"], "action": "accept"}
    ]
    tables = build_tables(run, decisions=decisions)
    assert _unmatched_rows(tables)[stmt_id] == "accepted pair missing from run"


def test_summary_counts_match_sheet_rows(run):
    tables = build_tables(run)
    summary = dict(tables["summary"][1:])
    assert summary["accepted_pairs"] == len(tables["matched_pairs"]) - 1
    assert summary["proposed_unreviewed_candidates"] == len(tables["proposed_unreviewed"]) - 1
    assert summary["unmatched_rows"] == len(tables["unmatched"]) - 1


def test_formula_injection_in_decision_reason_is_neutralised(run):
    candidate = _first_candidate(run)
    decisions = [
        {
            "id": 1,
            "stmt_line_id": candidate.stmt_line_id,
            "ledger_line_ids": list(candidate.ledger_line_ids),
            "action": "reject",
            "reason": "=SUM(A1:A9)",
        }
    ]
    tables = build_tables(run, decisions=decisions)
    assert tables["decisions"][1][4] == "'=SUM(A1:A9)"


def test_dash_prefixed_reason_is_neutralised(run):
    candidate = _first_candidate(run)
    decisions = [
        {
            "id": 1,
            "stmt_line_id": candidate.stmt_line_id,
            "ledger_line_ids": [],
            "action": "unmatch",
            "reason": "-1+1|calc",
        }
    ]
    tables = build_tables(run, decisions=decisions)
    assert tables["decisions"][1][4] == "'-1+1|calc"


def test_plain_cells_are_left_untouched(run):
    tables = build_tables(run)
    proposed = tables["proposed_unreviewed"]
    assert proposed[0][2] == "score"
    assert isinstance(proposed[1][2], (int, float)) and not isinstance(proposed[1][2], bool)
    assert proposed[1][3] == "auto_suggest"
    assert isinstance(proposed[1][4], int)
    assert isinstance(proposed[1][6], int)
    assert tables["unmatched"][1][0][0] != "'"
    assert tables["summary"][1][0] == "run_id"
