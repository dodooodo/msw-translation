"""Tests for TranslationPipeline in translation_pipeline.py.

Uses the "dummy" engine (returns originals unchanged) — no mocking needed.
Glossary integration is tested separately to verify the protect→restore chain.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from translation_pipeline import TranslationPipeline
from glossary_service import GlossaryService, GlossaryEntry

SRC = "Korean"
TGT = "Traditional Chinese"


@pytest.fixture
def dummy_config():
    return {
        "translator_engine": "dummy",
        "source_language": SRC,
        "target_language": TGT,
    }


@pytest.fixture
def pipeline(dummy_config):
    return TranslationPipeline(dummy_config)


@pytest.fixture
def glossary(tmp_path):
    return GlossaryService(path=str(tmp_path / "g.json"))


# ------------------------------------------------------------------
# Cache basics
# ------------------------------------------------------------------

def test_get_cached_miss(pipeline):
    assert pipeline.get_cached("hello") is None


def test_is_cached_false_before_translation(pipeline):
    assert not pipeline.is_cached("hello")


def test_translate_missing_warms_cache(pipeline):
    pipeline.translate_missing(["hello"])
    assert pipeline.get_cached("hello") is not None


def test_is_cached_true_after_translation(pipeline):
    pipeline.translate_missing(["hello"])
    assert pipeline.is_cached("hello")


def test_translate_returns_list_of_same_length(pipeline):
    results = pipeline.translate(["a", "b", "c"])
    assert isinstance(results, list)
    assert len(results) == 3


def test_translate_empty_list(pipeline):
    assert pipeline.translate([]) == []


def test_translate_missing_empty_list(pipeline):
    pipeline.translate_missing([])   # should not raise


def test_clear_cache(pipeline):
    pipeline.translate_missing(["hello"])
    pipeline.clear_cache()
    assert pipeline.get_cached("hello") is None


def test_clear_cache_resets_completely(pipeline):
    for w in ["alpha", "beta", "gamma"]:
        pipeline.translate_missing([w])
    pipeline.clear_cache()
    for w in ["alpha", "beta", "gamma"]:
        assert pipeline.get_cached(w) is None


# ------------------------------------------------------------------
# Dummy engine: translated == original
# ------------------------------------------------------------------

def test_dummy_engine_returns_original(pipeline):
    results = pipeline.translate(["테스트"])
    assert results[0] == "테스트"


def test_cache_hit_returns_same_value(pipeline):
    pipeline.translate_missing(["text"])
    first  = pipeline.get_cached("text")
    second = pipeline.get_cached("text")
    assert first == second


# ------------------------------------------------------------------
# Glossary integration
# ------------------------------------------------------------------

def test_glossary_protect_restore_in_pipeline(dummy_config, glossary):
    """
    With dummy engine, the placeholder passes through unchanged.
    restore() must substitute the target term into the cached result.
    """
    glossary.add_entry(GlossaryEntry(
        terms={SRC: "스타포스", TGT: "星之力"}
    ))
    p = TranslationPipeline(dummy_config, glossary=glossary)
    p.translate_missing(["캐릭터 스타포스 강화"])
    result = p.get_cached("캐릭터 스타포스 강화")
    assert result is not None
    assert "星之力" in result
    assert "스타포스" not in result


def test_no_glossary_does_not_crash(dummy_config):
    p = TranslationPipeline(dummy_config, glossary=None)
    results = p.translate(["hello"])
    assert results == ["hello"]


def test_set_glossary_clears_cache(dummy_config):
    p = TranslationPipeline(dummy_config)
    p.translate_missing(["text"])
    assert p.is_cached("text")
    p.set_glossary(None)
    assert not p.is_cached("text")


def test_pipeline_restores_single_bracket_placeholder_variant(dummy_config, glossary, monkeypatch):
    glossary.add_entry(GlossaryEntry(
        terms={SRC: "스타포스", TGT: "星之力"}
    ))
    p = TranslationPipeline(dummy_config, glossary=glossary)

    def fake_engine_translate(_texts, _config):
        return ["캐릭터 [T0] 강화"]

    monkeypatch.setattr("translation_pipeline.engine_translate", fake_engine_translate)
    p.translate_missing(["캐릭터 스타포스 강화"])
    assert p.get_cached("캐릭터 스타포스 강화") == "캐릭터 星之力 강화"


def test_pipeline_does_not_restore_bare_placeholder_token(dummy_config, glossary, monkeypatch):
    glossary.add_entry(GlossaryEntry(
        terms={SRC: "스타포스", TGT: "星之力"}
    ))
    p = TranslationPipeline(dummy_config, glossary=glossary)

    def fake_engine_translate(_texts, _config):
        return ["캐릭터 T0 강화"]

    monkeypatch.setattr("translation_pipeline.engine_translate", fake_engine_translate)
    p.translate_missing(["캐릭터 스타포스 강화"])
    assert p.get_cached("캐릭터 스타포스 강화") == "캐릭터 T0 강화"
