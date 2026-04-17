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
