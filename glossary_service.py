"""
glossary_service.py
Per-language-pair term substitution for the translation pipeline.
Pure Python — no Qt, no Quartz, no platform dependencies.

Glossary entries serve two roles in the pipeline:
  1. protect()  — replace source terms with placeholders BEFORE translation
                  so the engine cannot mangle game-specific proper nouns.
  2. restore()  — replace placeholders with target terms AFTER translation.
  3. correct()  — fallback string replacement for any entries whose placeholder
                  was lost or garbled by the engine.

Storage: glossary.json in the working directory.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field


GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.json")

# Placeholder format: unlikely to appear in natural text, preserved by most engines.
_PLACEHOLDER_FMT = "__T{i}__"


@dataclass
class GlossaryEntry:
    terms: dict[str, str] = field(default_factory=dict)
    match_mode: str = "exact"   # "exact" | "contains"  (regex: future)
    notes: str = ""


class GlossaryService:
    def __init__(self, path: str = GLOSSARY_PATH):
        self._path    = path
        self._entries: list[GlossaryEntry] = []
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load entries from disk. Safe to call even if the file doesn't exist."""
        if not os.path.exists(self._path):
            self._entries  = []
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            
            loaded_entries = []
            for e in data.get("entries", []):
                if "source_term" in e:
                    # Backward compatibility for old format
                    terms = {
                        e.get("source_lang", "Korean"): e.get("source_term", ""),
                        e.get("target_lang", "Traditional Chinese"): e.get("target_term", ""),
                    }
                    loaded_entries.append(GlossaryEntry(
                        terms=terms,
                        match_mode=e.get("match_mode", "exact"),
                        notes=e.get("notes", "")
                    ))
                else:
                    loaded_entries.append(GlossaryEntry(**e))
                    
            self._entries = loaded_entries
        except Exception as e:
            print(f"[Glossary] 載入失敗: {e}")
            self._entries = []

    def save(self) -> None:
        """Persist current entries to disk."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": [asdict(e) for e in self._entries]},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Glossary] 儲存失敗: {e}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_entries(self, source_lang: str, target_lang: str) -> list[GlossaryEntry]:
        """Return entries that have define both source and target terms."""
        return [e for e in self._entries
                if e.terms.get(source_lang) and e.terms.get(target_lang)]

    def get_all_entries(self) -> list[GlossaryEntry]:
        """Return all entries regardless of language pair."""
        return self._entries

    def set_all_entries(self, entries: list[GlossaryEntry]) -> None:
        """Replace the entire glossary, useful for bulk UI updates."""
        self._entries = entries
        self.save()

    def add_entry(self, entry: GlossaryEntry) -> None:
        """Add a single entry."""
        self._entries.append(entry)
        self.save()

    def remove_entry_by_term(self, term: str, lang: str) -> None:
        """Remove any entry having the precise term for the specified language."""
        self._entries = [e for e in self._entries if e.terms.get(lang) != term]
        self.save()

    # ------------------------------------------------------------------
    # Pipeline operations
    # ------------------------------------------------------------------

    def protect(
        self, text: str, source_lang: str, target_lang: str
    ) -> tuple[str, dict[str, str]]:
        """
        Replace source terms with numbered placeholders.
        Returns (protected_text, {placeholder: target_term}).
        Call restore() on the translated output to substitute them back.
        """
        entries = self.get_entries(source_lang, target_lang)
        placeholder_map: dict[str, str] = {}
        i = 0
        for entry in entries:
            src_term = entry.terms[source_lang]
            tgt_term = entry.terms[target_lang]
            ph = _PLACEHOLDER_FMT.format(i=i)
            pattern = self._build_pattern(src_term, entry.match_mode)
            
            if pattern and pattern.search(text):
                text = pattern.sub(ph, text)
                placeholder_map[ph] = tgt_term
                i += 1
        return text, placeholder_map

    def restore(self, text: str, placeholder_map: dict[str, str]) -> str:
        """Replace placeholders produced by protect() with their target terms."""
        for ph, target_term in placeholder_map.items():
            text = text.replace(ph, target_term)
        return text

    def correct(self, text: str, source_lang: str, target_lang: str) -> str:
        """
        Fallback correction pass: directly replace any incorrectly translated
        terms in the output. Applied after restore() as a safety net for
        placeholders the engine may have lost or garbled.
        """
        for entry in self.get_entries(source_lang, target_lang):
            tgt_term = entry.terms[target_lang]
            if tgt_term and tgt_term in text:
                continue   # already correct — skip
        return text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pattern(self, term: str, match_mode: str) -> re.Pattern | None:
        if not term:
            return None
        try:
            flags = 0  # case-sensitive by default for CJK / Korean
            if match_mode in ("exact", "contains"):
                # Split on whitespace so "A B" matches "AB", "A B", "A  B", etc.
                parts = [re.escape(p) for p in term.split()]
                pattern = r'\s*'.join(parts)
                return re.compile(pattern, flags)
        except re.error as e:
            print(f"[Glossary] 無效的 pattern '{term}': {e}")
        return None
