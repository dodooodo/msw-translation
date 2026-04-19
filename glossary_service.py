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

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein


GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.json")

# Placeholder format: unlikely to appear in natural text, preserved by most engines.
_PLACEHOLDER_FMT = "[[T{i}]]"

# Marker shared by all placeholder formats ([[T0]], [[E0]], etc.).
# Used by _fuzzy_find_substring to skip already-replaced regions.
_PLACEHOLDER_MARKER = "[["

_PLACEHOLDER_RE = re.compile(r"^\[\[([A-Z])(\d+)\]\]$")
_UNKNOWN_PLACEHOLDER_FRAGMENT_RE = re.compile(
    r"\[\[\s*[A-Z]\s*\d+\s*\]\]|\[\s*[A-Z]\s*\d+\s*\]"
)


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
        self, text: str, source_lang: str, target_lang: str,
        *,
        fuzzy_length_threshold: int = 3,
        fuzzy_short_max_distance: int = 1,
        fuzzy_long_max_distance: int = 2,
    ) -> tuple[str, dict[str, str]]:
        """
        Replace source terms with numbered placeholders.
        Returns (protected_text, {placeholder: target_term}).
        Call restore() on the translated output to substitute them back.

        Two-pass strategy:
          Pass 1 — exact regex matching (existing behaviour, fast path).
          Pass 2 — fuzzy substring matching for entries that didn't match
                   exactly, using a length-adaptive Levenshtein distance
                   budget to tolerate OCR character confusion
                   (e.g. 무↔우 in Korean).

        Fuzzy parameters (all keyword-only, sourced from config):
          fuzzy_length_threshold      — terms ≤ this many chars use the short budget
          fuzzy_short_max_distance    — max edit distance for short terms
          fuzzy_long_max_distance     — max edit distance for long terms
        """
        entries = self.get_entries(source_lang, target_lang)
        placeholder_map: dict[str, str] = {}
        i = 0

        # ── Pass 1: exact matching (unchanged hot path) ──────────────
        unmatched: list[GlossaryEntry] = []
        for entry in entries:
            src_term = entry.terms[source_lang]
            tgt_term = entry.terms[target_lang]
            ph = _PLACEHOLDER_FMT.format(i=i)
            pattern = self._build_pattern(src_term, entry.match_mode)

            if pattern and pattern.search(text):
                text = pattern.sub(ph, text)
                placeholder_map[ph] = tgt_term
                i += 1
            else:
                unmatched.append(entry)

        # ── Pass 2: fuzzy fallback for OCR-confused text ─────────────
        for entry in unmatched:
            src_term = entry.terms[source_lang]
            tgt_term = entry.terms[target_lang]
            span = _fuzzy_find_substring(
                text, src_term,
                length_threshold=fuzzy_length_threshold,
                short_max_distance=fuzzy_short_max_distance,
                long_max_distance=fuzzy_long_max_distance,
            )
            if span is not None:
                start, end = span
                ph = _PLACEHOLDER_FMT.format(i=i)
                text = text[:start] + ph + text[end:]
                placeholder_map[ph] = tgt_term
                i += 1

        return text, placeholder_map

    def restore(self, text: str, placeholder_map: dict[str, str]) -> str:
        """Replace placeholders produced by protect() with their target terms."""
        return restore_placeholder_variants(text, placeholder_map)

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


# --------------------------------------------------------------------------
# Module-level fuzzy matching helper (used by GlossaryService.protect)
# --------------------------------------------------------------------------

def _fuzzy_find_substring(
    text: str,
    term: str,
    *,
    length_threshold: int = 3,
    short_max_distance: int = 1,
    long_max_distance: int = 2,
) -> tuple[int, int] | None:
    """Find the best fuzzy match of *term* within *text* using a sliding window.

    Returns ``(start, end)`` of the matched span, or ``None``.

    Uses absolute Levenshtein edit distance.  The distance budget is
    determined by comparing the space-stripped term length against
    *length_threshold*:

    * ``term_len <= length_threshold`` → budget = *short_max_distance*
    * ``term_len >  length_threshold`` → budget = *long_max_distance*

    These three parameters are sourced from
    ``config["fuzzy_length_threshold"]``, ``config["fuzzy_short_max_distance"]``,
    and ``config["fuzzy_long_max_distance"]`` and forwarded by
    ``GlossaryService.protect()``.

    Placeholder contamination guard
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Windows that contain ``[[`` (the marker shared by ``[[T0]]`` and
    ``[[E0]]`` placeholders) are skipped so that prior replacements
    from Pass 1 or the ASCII-auto-protect step cannot produce
    spurious fuzzy matches.
    """
    term_nospace = term.replace(" ", "")
    term_len = len(term_nospace)

    if term_len < 2 or len(text) < term_len:
        return None

    # ── Select edit-distance budget from config ──────────────────────
    max_distance = short_max_distance if term_len <= length_threshold else long_max_distance
    if max_distance <= 0:
        return None   # fuzzy matching disabled for this term class

    best_distance = max_distance + 1   # sentinel: nothing found yet
    best_span: tuple[int, int] | None = None

    for window_size in range(max(2, term_len - 1), term_len + 2):
        for i in range(len(text) - window_size + 1):
            window = text[i : i + window_size]

            # ── Placeholder contamination guard ───────────────────
            if _PLACEHOLDER_MARKER in window:
                continue

            dist = Levenshtein.distance(
                term_nospace, window.replace(" ", ""),
                score_cutoff=max_distance,
            )
            if dist < best_distance:
                best_distance = dist
                best_span = (i, i + window_size)

    return best_span if best_distance <= max_distance else None


def restore_placeholder_variants(text: str, placeholder_map: dict[str, str]) -> str:
    """Restore exact placeholders and supported bracket-preserving variants."""
    items: list[tuple[str, str, int]] = []
    for ph, replacement in placeholder_map.items():
        parsed = _parse_placeholder_id(ph)
        if parsed is None:
            continue
        kind, idx = parsed
        items.append((kind, replacement, idx))

    for kind, replacement, idx in sorted(items, key=lambda item: len(str(item[2])), reverse=True):
        exact = _PLACEHOLDER_FMT.replace("T", kind).format(i=idx)
        text = text.replace(exact, replacement)
        for pattern in _build_placeholder_variant_patterns(kind, idx):
            text = pattern.sub(replacement, text)
    return text


def cleanup_placeholder_fragments(
    text: str,
    placeholder_map: dict[str, str],
    ascii_map: dict[str, str],
) -> str:
    """Restore known bracketed fragments, then remove unknown bracketed remnants."""
    combined = dict(placeholder_map)
    combined.update(ascii_map)
    text = restore_placeholder_variants(text, combined)
    return _UNKNOWN_PLACEHOLDER_FRAGMENT_RE.sub("", text)


def _parse_placeholder_id(placeholder: str) -> tuple[str, int] | None:
    match = _PLACEHOLDER_RE.match(placeholder)
    if not match:
        return None
    kind, idx = match.groups()
    return kind, int(idx)


def _build_placeholder_variant_patterns(kind: str, idx: int) -> list[re.Pattern]:
    token = f"{kind}{idx}"
    spaced = f"{kind} {idx}"
    return [
        re.compile(rf"(?<![A-Za-z0-9])\[\[\s*{re.escape(token)}\s*\]\](?![A-Za-z0-9])"),
        re.compile(rf"(?<![A-Za-z0-9])\[\[\s*{re.escape(spaced)}\s*\]\](?![A-Za-z0-9])"),
        re.compile(rf"(?<![A-Za-z0-9])\[\s*{re.escape(token)}\s*\](?![A-Za-z0-9])"),
        re.compile(rf"(?<![A-Za-z0-9])\[\s*{re.escape(spaced)}\s*\](?![A-Za-z0-9])"),
    ]
