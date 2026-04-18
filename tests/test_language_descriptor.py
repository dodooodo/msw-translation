"""Tests for language_descriptor.py — pure metadata, no deps."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from language_descriptor import LanguageDescriptor, LANGUAGES, get


def test_all_expected_languages_present():
    expected = {"Korean", "Japanese", "English",
                "Traditional Chinese", "Simplified Chinese"}
    assert expected.issubset(LANGUAGES.keys())


def test_display_name_matches_key():
    for name, desc in LANGUAGES.items():
        assert desc.display_name == name


def test_cjk_languages_are_asian():
    for name in ("Korean", "Japanese",
                 "Traditional Chinese", "Simplified Chinese"):
        assert LANGUAGES[name].asian is True


def test_english_is_not_asian():
    assert LANGUAGES["English"].asian is False


def test_english_uses_end_punctuation_but_cjk_does_not():
    assert LANGUAGES["English"].use_end_punctuation is True
    for name in ("Korean", "Japanese",
                 "Traditional Chinese", "Simplified Chinese"):
        assert LANGUAGES[name].use_end_punctuation is False


def test_korean_does_not_remove_spaces():
    # Korean writes with spaces between eojeols, unlike Chinese/Japanese.
    assert LANGUAGES["Korean"].use_space_remover is False


def test_chinese_and_japanese_remove_spaces():
    for name in ("Japanese", "Traditional Chinese", "Simplified Chinese"):
        assert LANGUAGES[name].use_space_remover is True


def test_ocr_languages_are_tuples():
    for desc in LANGUAGES.values():
        assert isinstance(desc.ocr_languages, tuple)
        assert len(desc.ocr_languages) >= 1


def test_traditional_and_simplified_chinese_differ():
    assert LANGUAGES["Traditional Chinese"].ocr_languages == ("zh-Hant",)
    assert LANGUAGES["Simplified Chinese"].ocr_languages == ("zh-Hans",)


def test_get_returns_descriptor():
    desc = get("Korean")
    assert isinstance(desc, LanguageDescriptor)
    assert desc.display_name == "Korean"


def test_get_unknown_falls_back_to_korean():
    # Unknown names must not raise — config.json evolves over time.
    desc = get("Klingon")
    assert desc.display_name == "Korean"


def test_descriptor_is_frozen():
    # Prevent accidental mutation of shared metadata.
    with pytest.raises(Exception):
        LANGUAGES["Korean"].asian = False  # type: ignore[misc]


def test_ocr_lang_map_matches_language_descriptors():
    """OCR_LANG_MAP in ocr/__init__.py must stay in sync with LANGUAGES."""
    from ocr import OCR_LANG_MAP
    for name, desc in LANGUAGES.items():
        assert OCR_LANG_MAP[name] == list(desc.ocr_languages)
