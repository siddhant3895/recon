import pytest

from recon.similarity import jaro_winkler, ref_similarity, refs_overlap, token_set_ratio


def test_jaro_winkler_bounds():
    assert jaro_winkler("", "") == 1.0
    assert jaro_winkler("abc", "") == 0.0
    assert jaro_winkler("12345678", "12345678") == 1.0


def test_jaro_winkler_near_reference():
    assert jaro_winkler("12345678", "12345679") >= 0.9
    assert jaro_winkler("12345678", "99999999") < 0.5


def test_jaro_winkler_matches_reference_vectors():
    assert jaro_winkler("MARTHA", "MARHTA") == pytest.approx(0.9611, abs=1e-4)
    assert jaro_winkler("DIXON", "DICKSONX") == pytest.approx(0.8133, abs=1e-4)
    assert jaro_winkler("DWAYNE", "DUANE") == pytest.approx(0.84, abs=1e-4)


def test_token_set_ratio_empty_texts_score_zero():
    assert token_set_ratio("", "") == 0.0
    assert token_set_ratio("the of", "and by") == 0.0


def test_token_set_ratio_keeps_raw_tokens_when_text_is_all_stopwords():
    assert token_set_ratio("the of", "the of") == 1.0


def test_token_set_ratio_is_dice_on_sets():
    assert token_set_ratio("sharma traders invoice", "sharma traders invoice") == 1.0
    assert token_set_ratio("sharma traders", "orange packaging") == 0.0
    assert token_set_ratio("sharma traders 42", "sharma traders 43") == pytest.approx(2 * 2 / 6)


def test_reference_helpers_use_tokens_not_whole_strings():
    assert refs_overlap("5000001042 12345678", "12345678") is True
    assert refs_overlap("11111111", "22222222") is False
    assert ref_similarity("5000001042 12345678", "12345678") == 1.0
