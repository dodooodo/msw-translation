"""Tests for GlossaryService in glossary_service.py."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import pytest
from glossary_service import GlossaryService, GlossaryEntry

SRC = "Korean"
TGT = "Traditional Chinese"


def _entry(source_term: str, target_term: str = "翻譯", notes: str = "") -> GlossaryEntry:
    return GlossaryEntry(
        terms={SRC: source_term, TGT: target_term},
        notes=notes,
    )


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------

def test_load_missing_file(tmp_path):
    g = GlossaryService(path=str(tmp_path / "none.json"))
    assert g.get_entries(SRC, TGT) == []


def test_add_and_get_entries(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("스타포스", "星之力"))
    entries = g.get_entries(SRC, TGT)
    assert len(entries) == 1
    assert entries[0].terms[SRC] == "스타포스"
    assert entries[0].terms[TGT] == "星之力"


def test_remove_entry(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("X", "x"))
    g.add_entry(_entry("Y", "y"))
    g.remove_entry_by_term("X", SRC)
    entries = g.get_entries(SRC, TGT)
    assert len(entries) == 1
    assert entries[0].terms[SRC] == "Y"


def test_get_entries_filters_by_lang_pair(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("KR", "TW"))     # Korean → Traditional Chinese
    g.add_entry(GlossaryEntry(
        terms={"English": "EN", TGT: "TW"}
    ))
    assert len(g.get_entries(SRC, TGT)) == 1
    assert len(g.get_entries("English", TGT)) == 1
    assert len(g.get_entries("Japanese", TGT)) == 0


def test_save_and_reload(tmp_path):
    path = str(tmp_path / "g.json")
    g1 = GlossaryService(path=path)
    g1.add_entry(_entry("스타포스", "星之力"))

    g2 = GlossaryService(path=path)       # fresh instance, same file
    entries = g2.get_entries(SRC, TGT)
    assert len(entries) == 1
    assert entries[0].terms[TGT] == "星之力"


def test_save_json_structure(tmp_path):
    path = str(tmp_path / "g.json")
    g = GlossaryService(path=path)
    g.add_entry(_entry("A", "B", notes="note"))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == 1
    assert len(data["entries"]) == 1
    assert data["entries"][0]["notes"] == "note"


# ------------------------------------------------------------------
# protect / restore
# ------------------------------------------------------------------

def test_protect_single_term(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("스타포스", "星之力"))
    text, pmap = g.protect("캐릭터 스타포스 강화", SRC, TGT)
    assert "스타포스" not in text
    assert "__T0__" in text
    assert pmap["__T0__"] == "星之力"


def test_protect_multiple_terms(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("아이템", "道具"))
    g.add_entry(_entry("스타포스", "星之力"))
    text, pmap = g.protect("스타포스 아이템 강화", SRC, TGT)
    assert "스타포스" not in text
    assert "아이템" not in text
    assert len(pmap) == 2


def test_protect_no_match(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("스타포스", "星之力"))
    text, pmap = g.protect("완전 다른 텍스트", SRC, TGT)
    assert text == "완전 다른 텍스트"
    assert pmap == {}


def test_restore(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    result = g.restore("캐릭터 __T0__ 강화", {"__T0__": "星之力"})
    assert result == "캐릭터 星之力 강화"


def test_protect_restore_roundtrip(tmp_path):
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("스타포스", "星之力"))
    original = "캐릭터 스타포스 강화"
    protected, pmap = g.protect(original, SRC, TGT)
    # Simulate dummy engine: output == protected (placeholder survives)
    restored = g.restore(protected, pmap)
    assert "星之力" in restored
    assert "스타포스" not in restored


# ------------------------------------------------------------------
# fuzzy fallback (Pass 2 — OCR character confusion tolerance)
# ------------------------------------------------------------------

def test_protect_fuzzy_single_char_error(tmp_path):
    """OCR confuses 우→무: '듀얼 보무건' should still match '듀얼 보우건'."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("듀얼 보우건", "雙弩槍"))
    text, pmap = g.protect("듀얼 보무건", SRC, TGT)
    assert len(pmap) == 1
    assert "雙弩槍" in pmap.values()
    assert "보무건" not in text


def test_protect_fuzzy_short_term_single_error(tmp_path):
    """3-char term with 1 OCR error should match (67% > 66% threshold)."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("공격력", "攻擊力"))
    text, pmap = g.protect("공겨력 증가", SRC, TGT)
    assert len(pmap) == 1
    assert "攻擊力" in pmap.values()


def test_protect_fuzzy_skips_single_char_terms(tmp_path):
    """Single-char terms are too short for fuzzy — should not match."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("무", "武"))
    text, pmap = g.protect("우", SRC, TGT)
    assert pmap == {}
    assert text == "우"


def test_protect_fuzzy_no_false_positive(tmp_path):
    """Completely unrelated text must not fuzzy-match a glossary entry."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("듀얼 보우건", "雙弩槍"))
    text, pmap = g.protect("완전 다른 텍스트입니다", SRC, TGT)
    assert pmap == {}


def test_protect_exact_preferred_over_fuzzy(tmp_path):
    """When text matches exactly, exact path wins (Pass 1 before Pass 2)."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("스타포스", "星之力"))
    text, pmap = g.protect("스타포스 강화", SRC, TGT)
    assert len(pmap) == 1
    assert "__T0__" in text


def test_protect_fuzzy_threshold_boundary(tmp_path):
    """2-char term with 1 error = distance 1 = max_distance: should still match.
    A 2-char term with 2 errors (beyond budget) should be rejected."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("전사", "劍士"))
    # 1 error in 2-char term = distance 1 = exactly at budget → matches
    text1, pmap1 = g.protect("전시", SRC, TGT)
    assert len(pmap1) == 1   # distance 1 == max_distance(1) → accepted
    # Completely different 2-char term = distance 2 > budget → rejected
    text2, pmap2 = g.protect("기도", SRC, TGT)
    assert pmap2 == {}       # distance 2 > max_distance(1) for ≤3-char → rejected


def test_protect_fuzzy_placeholder_not_contaminated(tmp_path):
    """Pass 1 placeholders must not interfere with Pass 2 fuzzy scan."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("아이템", "道具"))           # exact match
    g.add_entry(_entry("듀얼 보우건", "雙弩槍"))    # will need fuzzy
    text, pmap = g.protect("아이템 듀얼 보무건", SRC, TGT)
    assert "道具" in pmap.values()      # exact matched
    assert "雙弩槍" in pmap.values()    # fuzzy matched
    assert len(pmap) == 2


def test_protect_fuzzy_restore_roundtrip(tmp_path):
    """Full roundtrip: fuzzy protect → dummy engine → restore."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("소비아이템", "消耗品"))
    # OCR error: 탬 instead of 템
    protected, pmap = g.protect("소비아이탬 사용", SRC, TGT)
    assert len(pmap) == 1
    restored = g.restore(protected, pmap)
    assert "消耗品" in restored


def test_protect_fuzzy_two_char_errors(tmp_path):
    """Real-world case: OCR produces 듀멀 보무건 (2 errors: 얼→멀, 우→무).
    With max_distance=2 for >3-char terms this should now match."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("듀얼 보우건", "雙弩槍"))
    text, pmap = g.protect("듀멀 보무건", SRC, TGT)
    assert len(pmap) == 1
    assert "雙弩槍" in pmap.values()


def test_protect_fuzzy_two_errors_in_longer_text(tmp_path):
    """2 OCR errors in a 5-char term embedded in a longer sentence."""
    g = GlossaryService(path=str(tmp_path / "g.json"))
    g.add_entry(_entry("듀얼 보우건", "雙弩槍"))
    g.add_entry(_entry("공격력", "攻擊力"))
    g.add_entry(_entry("주문서", "捲軸"))
    text, pmap = g.protect("듀멀 보무건 공격력 주문서", SRC, TGT)
    assert "雙弩槍" in pmap.values()
    assert "攻擊力" in pmap.values()
    assert "捲軸" in pmap.values()
