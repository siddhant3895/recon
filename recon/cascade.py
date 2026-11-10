from __future__ import annotations

from bisect import bisect_left, bisect_right

from .models import Candidate, Line
from .scoring import (
    amount_band_paise,
    date_window_days,
    score_candidate,
)
from .similarity import jaro_winkler, ref_similarity, refs_overlap, token_set_ratio

TIER_CANDIDATE_CAP = {1: None, 2: 5, 3: 3, 4: 3}
TIER4_MAX_LINES = 4
TIER4_NODE_CAP = 5000


class _NodeCapExceeded(RuntimeError):
    pass


class Cascade:
    def __init__(self, stmt_lines: list[Line], ledger_lines: list[Line], node_cap: int = TIER4_NODE_CAP):
        self.stmt_lines = sorted(stmt_lines, key=lambda line: line.id)
        self.ledger_lines = sorted(ledger_lines, key=lambda line: line.id)
        self.node_cap = node_cap
        self.tier4_abandoned = 0
        self.tier4_nodes = 0

        self.by_amount: dict[int, list[Line]] = {}
        for line in self.ledger_lines:
            self.by_amount.setdefault(line.amount_paise, []).append(line)
        for rows in self.by_amount.values():
            rows.sort(key=lambda line: (line.date, line.id))

        self.sorted_amounts = sorted(self.by_amount)
        self.by_direction: dict[str, list[Line]] = {"debit": [], "credit": []}
        for line in self.ledger_lines:
            self.by_direction[line.direction].append(line)
        for rows in self.by_direction.values():
            rows.sort(key=lambda line: (line.date, line.id))

    def run(self) -> dict[str, list[Candidate]]:
        return {stmt.id: self.match_line(stmt) for stmt in self.stmt_lines}

    def match_line(self, stmt: Line) -> list[Candidate]:
        for tier in (1, 2, 3, 4):
            sets = self._tier_sets(stmt, tier)
            if not sets:
                continue
            candidates = self._score_sets(stmt, sets, tier)
            cap = TIER_CANDIDATE_CAP[tier]
            if cap is not None:
                candidates = candidates[:cap]
            if candidates:
                return candidates
        return []

    def _score_sets(self, stmt: Line, sets: list[list[Line]], tier: int) -> list[Candidate]:
        seen: set[tuple[str, ...]] = set()
        candidates: list[Candidate] = []
        for lines in sets:
            ids = tuple(sorted(line.id for line in lines))
            if ids in seen:
                continue
            seen.add(ids)
            candidates.append(score_candidate(stmt, sorted(lines, key=lambda line: line.id), tier))
        candidates.sort(key=lambda candidate: (-candidate.score, tuple(candidate.ledger_line_ids), candidate.tier))
        return candidates

    def _tier_sets(self, stmt: Line, tier: int) -> list[list[Line]]:
        if tier == 1:
            return self._tier1(stmt)
        if tier == 2:
            return self._tier2(stmt)
        if tier == 3:
            return self._tier3(stmt)
        return self._tier4(stmt)

    def _tier1(self, stmt: Line) -> list[list[Line]]:
        matches: list[list[Line]] = []
        for ledger in self.by_amount.get(stmt.amount_paise, ()):
            if ledger.direction != stmt.direction:
                continue
            if not refs_overlap(stmt.ref_token, ledger.ref_token):
                continue
            window = date_window_days(1, stmt, [ledger])
            if abs((ledger.date - stmt.date).days) > window:
                continue
            matches.append([ledger])
        return matches

    def _tier2(self, stmt: Line) -> list[list[Line]]:
        if not stmt.ref_token:
            return []
        matches: list[list[Line]] = []
        for ledger in self.by_amount.get(stmt.amount_paise, ()):
            if ledger.direction != stmt.direction or not ledger.ref_token:
                continue
            if ref_similarity(stmt.ref_token, ledger.ref_token) < 0.85:
                continue
            window = date_window_days(2, stmt, [ledger])
            if abs((ledger.date - stmt.date).days) > window:
                continue
            matches.append([ledger])
        return matches

    def _tier3(self, stmt: Line) -> list[list[Line]]:
        band = amount_band_paise(stmt.amount_paise, 3)
        low = stmt.amount_paise - band
        high = stmt.amount_paise + band
        start = bisect_left(self.sorted_amounts, low)
        end = bisect_right(self.sorted_amounts, high)
        matches: list[list[Line]] = []
        for amount in self.sorted_amounts[start:end]:
            for ledger in self.by_amount[amount]:
                if ledger.direction != stmt.direction:
                    continue
                window = date_window_days(3, stmt, [ledger])
                if abs((ledger.date - stmt.date).days) > window:
                    continue
                if token_set_ratio(stmt.text_norm, ledger.text_norm) < 0.6:
                    continue
                matches.append([ledger])
        return matches

    def _tier4(self, stmt: Line) -> list[list[Line]]:
        tolerance = amount_band_paise(stmt.amount_paise, 4)
        pool: list[Line] = []
        for ledger in self.by_direction[stmt.direction]:
            window = date_window_days(4, stmt, [ledger])
            if abs((ledger.date - stmt.date).days) > window:
                continue
            if ledger.amount_paise > stmt.amount_paise + tolerance:
                continue
            pool.append(ledger)
        if len(pool) < 2:
            return []

        pool.sort(
            key=lambda line: (
                -token_set_ratio(stmt.text_norm, line.text_norm),
                abs((line.date - stmt.date).days),
                line.amount_paise,
                line.id,
            )
        )

        target = stmt.amount_paise
        results: list[list[Line]] = []
        search_cap = 50
        nodes = 0
        chosen: list[Line] = []

        def search(start: int, total: int) -> bool:
            nonlocal nodes
            if len(chosen) >= 2 and abs(total - target) <= tolerance:
                results.append(list(chosen))
                return len(results) >= search_cap
            if len(chosen) == TIER4_MAX_LINES:
                return False
            for index in range(start, len(pool)):
                nodes += 1
                if nodes > self.node_cap:
                    raise _NodeCapExceeded
                candidate_total = total + pool[index].amount_paise
                if candidate_total > target + tolerance:
                    continue
                chosen.append(pool[index])
                if search(index + 1, candidate_total):
                    chosen.pop()
                    return True
                chosen.pop()
            return False

        try:
            search(0, 0)
        except _NodeCapExceeded:
            self.tier4_abandoned += 1
            self.tier4_nodes += nodes
            return []

        self.tier4_nodes += nodes
        return results
