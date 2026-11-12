"""String similarity primitives used by the scoring engine.

Formulas:

- ``jaro_winkler`` implements the standard Jaro-Winkler similarity: the Jaro
  similarity with a bonus of 0.1 per matching prefix character over the first
  four characters, capped at 1.0. Identical strings score 1.0; a string
  compared against an empty string scores 0.0.
- ``token_set_ratio`` computes the Dice coefficient over the whitespace token
  sets of the two texts: ``2 * |A ∩ B| / (|A| + |B|)``. Stopwords are removed
  from both token sets unless a text consists entirely of stopwords, in which
  case the raw tokens are kept. Two texts that both reduce to no tokens score
  0.0, because empty narrations carry no evidence of a match.
"""

from __future__ import annotations

_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "inv",
    "invoice",
    "of",
    "payment",
    "pymt",
    "ref",
    "the",
    "to",
    "towards",
    "transaction",
    "transfer",
    "txn",
    "upi",
    "neft",
    "rtgs",
    "imps",
    "chq",
    "clg",
    "atm",
    "pos",
    "ach",
}


def jaro_winkler(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0

    len_left = len(left)
    len_right = len(right)
    match_distance = max(len_left, len_right) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    left_matches = [False] * len_left
    right_matches = [False] * len_right
    matches = 0

    for i, char in enumerate(left):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len_right)
        for j in range(start, end):
            if not right_matches[j] and right[j] == char:
                left_matches[i] = True
                right_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    transpositions = 0
    k = 0
    for i in range(len_left):
        if left_matches[i]:
            while not right_matches[k]:
                k += 1
            if left[i] != right[k]:
                transpositions += 1
            k += 1
    transpositions //= 2

    jaro = (
        matches / len_left
        + matches / len_right
        + (matches - transpositions) / matches
    ) / 3.0

    prefix = 0
    for left_char, right_char in zip(left[:4], right[:4]):
        if left_char != right_char:
            break
        prefix += 1

    return min(1.0, jaro + prefix * 0.1 * (1.0 - jaro))


def _tokens(text: str) -> set[str]:
    raw = {token for token in text.split() if token}
    filtered = raw - _STOPWORDS
    return filtered or raw


def token_set_ratio(left: str, right: str) -> float:
    """Dice coefficient over the two token sets; 0.0 when neither text has tokens."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    return (2.0 * intersection) / (len(left_tokens) + len(right_tokens))


def ref_tokens(ref_token: str) -> list[str]:
    return [token for token in ref_token.split() if token]


def ref_similarity(left: str, right: str) -> float:
    left_tokens = ref_tokens(left)
    right_tokens = ref_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    best = 0.0
    for left_token in left_tokens:
        for right_token in right_tokens:
            best = max(best, jaro_winkler(left_token, right_token))
    return best


def refs_overlap(left: str, right: str) -> bool:
    return bool(set(ref_tokens(left)) & set(ref_tokens(right)))
