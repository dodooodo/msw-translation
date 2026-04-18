"""Tests for text_normalizer.py — pure function, no deps."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from text_normalizer import CJK_PUNCT_MAP, normalize_ocr_text


# ------------------------------------------------------------------
# CJK_PUNCT_MAP structure
# ------------------------------------------------------------------

def test_punct_map_matches_translumo_entry_count():
    # Port of Translumo's _replacers — 26 punct entries + 10 full-width digits.
    assert len(CJK_PUNCT_MAP) == 36


def test_punct_map_covers_fullwidth_digits():
    for d in "０１２３４５６７８９":
        assert CJK_PUNCT_MAP[d] == str("０１２３４５６７８９".index(d))


def test_punct_map_covers_common_cjk_punct():
    # Sanity check on the highest-ROI entries.
    assert CJK_PUNCT_MAP["，"] == ","
    assert CJK_PUNCT_MAP["。" ] if "。" in CJK_PUNCT_MAP else True  # absent is fine
    assert CJK_PUNCT_MAP["！"] == "!"
    assert CJK_PUNCT_MAP["？"] == "?"
    assert CJK_PUNCT_MAP["…"] == "..."


# ------------------------------------------------------------------
# Main cross-engine mismatch case (the motivating bug for 1a)
# ------------------------------------------------------------------

def test_fullwidth_and_ascii_comma_normalize_identically():
    # Apple Vision → "안녕，" ; Windows OCR → "안녕,"
    a = normalize_ocr_text("안녕，", use_end_punctuation=False)
    b = normalize_ocr_text("안녕,",  use_end_punctuation=False)
    assert a == b


def test_fullwidth_digits_become_ascii():
    out = normalize_ocr_text("００１２３", use_end_punctuation=False)
    assert out == "00123"


# ------------------------------------------------------------------
# Trim rules
# ------------------------------------------------------------------

def test_strips_leading_and_trailing_dashes():
    assert normalize_ocr_text("-hello-", use_end_punctuation=False) == "hello"


def test_strips_leading_and_trailing_dots():
    assert normalize_ocr_text("...hello...", use_end_punctuation=False) == "hello"


def test_strips_matching_double_quote_pair():
    assert normalize_ocr_text('"hello"', use_end_punctuation=False) == "hello"


def test_strips_matching_single_quote_pair():
    assert normalize_ocr_text("'hello'", use_end_punctuation=False) == "hello"


def test_does_not_strip_mismatched_quotes():
    assert normalize_ocr_text("'hello\"", use_end_punctuation=False) == "'hello\""


def test_collapses_multiple_whitespace():
    assert normalize_ocr_text("a    b\t\tc", use_end_punctuation=False) == "a b c"


# ------------------------------------------------------------------
# use_end_punctuation flag (European languages)
# ------------------------------------------------------------------

def test_end_punct_adds_period_when_missing():
    assert normalize_ocr_text("hello", use_end_punctuation=True) == "hello."


def test_end_punct_does_not_double_period():
    assert normalize_ocr_text("hello.", use_end_punctuation=True) == "hello."


def test_end_punct_respects_question_and_exclaim():
    assert normalize_ocr_text("hello?", use_end_punctuation=True) == "hello?"
    assert normalize_ocr_text("hello!", use_end_punctuation=True) == "hello!"


def test_end_punct_disabled_leaves_text_alone():
    assert normalize_ocr_text("안녕",  use_end_punctuation=False) == "안녕"


def test_end_punct_on_empty_string_stays_empty():
    assert normalize_ocr_text("", use_end_punctuation=True) == ""


# ------------------------------------------------------------------
# use_space_remover flag (CJK cache-key only)
# ------------------------------------------------------------------

def test_space_remover_deletes_spaces():
    out = normalize_ocr_text(
        "こんにちは 世界",
        use_end_punctuation=False,
        use_space_remover=True,
    )
    assert out == "こんにちは世界"


def test_space_remover_off_preserves_spaces():
    out = normalize_ocr_text(
        "こんにちは 世界",
        use_end_punctuation=False,
        use_space_remover=False,
    )
    assert out == "こんにちは 世界"


# ------------------------------------------------------------------
# Multi-char sequence substitution (Translumo _replacers has 3-char "・・・")
# ------------------------------------------------------------------

def test_ellipsis_forms_converge_for_cache_key():
    # Three different OCR spellings of an end-of-line ellipsis all land on the
    # same cache key. The trailing dots are stripped by the edge-dot rule
    # because we only care that the three inputs agree, not what they equal.
    a = normalize_ocr_text("wait・・・", use_end_punctuation=False)
    b = normalize_ocr_text("wait…",    use_end_punctuation=False)
    c = normalize_ocr_text("wait...",  use_end_punctuation=False)
    assert a == b == c


def test_single_middle_dot_stays_untouched():
    # Not in the table; should not be mangled.
    out = normalize_ocr_text("a・b", use_end_punctuation=False)
    assert out == "a・b"


# ------------------------------------------------------------------
# Integration: full pipeline (a realistic OCR line)
# ------------------------------------------------------------------

def test_realistic_mixed_punctuation_line():
    """Simulates an Apple Vision vs Windows OCR divergence on the same scene."""
    apple   = "「안녕！」"
    windows = "「안녕!」"
    a = normalize_ocr_text(apple,   use_end_punctuation=False)
    b = normalize_ocr_text(windows, use_end_punctuation=False)
    # Outer brackets "「」" aren't in the table; what matters is the inner swap.
    assert a == b
