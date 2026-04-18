"""
translation_pipeline.py
Owns the full translation lifecycle: pre-process → engine → post-process + LRU cache.
Pure Python — no Qt, no Quartz, no platform dependencies.

Designed for two input sources:
  1. OCRWorker  — feeds raw OCR text blocks
  2. Future user-typed input — sends text directly without OCR

Both sources call the same pipeline instance injected by AppController.

Performance model
-----------------
~95 % of frames in active gaming produce text the engine has already seen.
Cache key = raw OCR text (before pre-processing).
Cache value = fully post-processed final result.
→ Cache hit: pure O(1) dict lookup, zero glossary overhead.
→ Cache miss: full pipeline runs once and is never repeated for that text.
"""

from __future__ import annotations

import threading
import re
import unicodedata

from translator_engine import LRUCache, engine_translate
from glossary_service  import GlossaryService
from language_descriptor import get as get_language
from text_normalizer    import normalize_ocr_text


# Unicode ranges that indicate actual source-language content worth translating.
# Anything outside these ranges (ASCII, Latin-1 supplement like ¾/£, emoji,
# currency symbols, etc.) is treated as non-translatable noise.
_SOURCE_LANG_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "Korean":              ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)),
    "Japanese":            ((0x3040, 0x309F), (0x30A0, 0x30FF), (0x4E00, 0x9FFF)),
    "Traditional Chinese": ((0x4E00, 0x9FFF), (0x3400, 0x4DBF)),
    "Simplified Chinese":  ((0x4E00, 0x9FFF), (0x3400, 0x4DBF)),
}


def has_source_content(text: str, source_lang: str) -> bool:
    """True if `text` contains at least one character in the source language's
    script. For English source, any letter counts. Used to skip OCR noise like
    '¾', '£', or pure-ASCII UI elements that shouldn't hit the engine."""
    if source_lang == "English":
        return any(c.isalpha() and ord(c) < 128 for c in text)
    ranges = _SOURCE_LANG_RANGES.get(source_lang)
    if ranges is None:
        return True
    return any(lo <= ord(c) <= hi for c in text for lo, hi in ranges)


class TranslationPipeline:
    """
    Thread-safe for the intended usage pattern:
      - One OCRWorker background thread calls translate_missing().
      - One or more readers call get_cached() from any thread.
    translate_missing() writes to the cache atomically per entry via LRUCache.put(),
    which is protected by the GIL. No explicit lock needed for this use case.
    """

    def __init__(self, config: dict, glossary: GlossaryService | None = None):
        # config is a shared dict — mutate it in-place from the main thread
        # and the pipeline sees the update immediately on the next tick.
        self.config   = config
        self.glossary = glossary
        self._cache   = LRUCache(3000)
        self._lock    = threading.Lock()   # guards cache replacement in clear_cache

    # ------------------------------------------------------------------
    # Text normalization (applied to cache keys only, not translated content)
    # ------------------------------------------------------------------

    def _normalize(self, text: str) -> str:
        """
        Canonicalize OCR text for use as a cache key.
        Increases cache hit rate when Vision OCR produces minor variations
        of the same visual content across frames.

        Applied to keys only — the original raw text is stored as the cache value.
        """
        # 1. NFC: combines decomposed Hangul jamo into precomposed syllables
        text = unicodedata.normalize("NFC", text)
        # 2. Legacy edge-char trim — Vision sometimes adds stray marks at edges
        text = text.strip("·•—…ㅡㅣ")
        # 3. Collapse repeated CJK/punctuation (e.g. "!!" → "!")
        text = re.sub(r'([。、！？·])\1+', r'\1', text)
        # 4. Translumo-style CJK normalisation: punctuation swap, dot/quote
        #    trim, whitespace collapse, optional language-specific tweaks.
        desc = get_language(self.config.get("source_language", "Korean"))
        text = normalize_ocr_text(
            text,
            is_asian=desc.asian,
            use_end_punctuation=desc.use_end_punctuation,
            use_space_remover=desc.use_space_remover,
        )
        return text

    # ------------------------------------------------------------------
    # Cache access (hot path — called every OCR tick)
    # ------------------------------------------------------------------

    # Fuzzy-match thresholds on rapidfuzz.fuzz.ratio's 0–100 scale.  Asian
    # scripts lose fewer characters to OCR jitter per symbol than Latin text,
    # so a tighter threshold is safe there; Translumo uses the same split
    # (0.80 vs 0.65 on Jaro) for the same reason.
    _FUZZY_THRESHOLD_ASIAN    = 95.0
    _FUZZY_THRESHOLD_NONASIAN = 90.0

    def get_cached(self, raw_text: str) -> str | None:
        """O(1) lookup, with a fuzzy fallback for jittery OCR output.

        Exact-normalized match is tried first.  On miss, rapidfuzz scans the
        most recent cache entries; if one is similar enough, its translation
        is returned AND written back under the current key so future lookups
        for the same jitter become O(1).
        """
        key = self._normalize(raw_text)
        exact = self._cache.get(key)
        if exact is not None:
            return exact

        desc = get_language(self.config.get("source_language", "Korean"))
        threshold = (self._FUZZY_THRESHOLD_ASIAN
                     if desc.asian else self._FUZZY_THRESHOLD_NONASIAN)
        fuzzy = self._cache.get_or_similar(key, threshold=threshold)
        if fuzzy is not None:
            # Warm the exact key so next frame's lookup is O(1).
            self._cache.put(key, fuzzy)
        return fuzzy

    def is_cached(self, raw_text: str) -> bool:
        return self.get_cached(raw_text) is not None

    # ------------------------------------------------------------------
    # Translation (cold path — called only on cache miss, in background thread)
    # ------------------------------------------------------------------

    def translate_missing(self, raw_texts: list[str]) -> None:
        """
        Translate a batch of texts that are NOT yet in the cache.
        Runs the full pipeline: protect → engine → restore → correct.
        Warms the cache so subsequent get_cached() calls return immediately.

        Called from a background thread. Does not return results directly;
        callers poll get_cached() after this completes.
        """
        if not raw_texts:
            return

        source_lang = self.config.get("source_language", "Korean")
        target_lang = self.config.get("target_language", "Traditional Chinese")

        # ---- Stage 1: Pre-process (glossary term protection) ----
        texts_to_translate: list[str] = []
        protected_texts: list[str] = []
        placeholder_maps: list[dict[str, str]] = []
        ascii_maps: list[dict[str, str]] = []
        
        import re
        # Matches any continuous ASCII sequence starting and ending with an alphanumeric character
        ascii_pattern = re.compile(r'[A-Za-z0-9](?:[\x20-\x7E]*[A-Za-z0-9])?')

        for text in raw_texts:
            # Skip translation for strings with no source-language content
            # (pure ASCII, Latin-1 glyphs like ¾/£, symbols, emoji, etc.)
            if not has_source_content(text, source_lang):
                self._cache.put(self._normalize(text), text)
                continue

            texts_to_translate.append(text)
            
            protected = text
            pmap = {}
            e_pmap = {}
            
            # --- Auto-protect embedded English/Numbers ---
            if source_lang != "English":
                e_index = 0
                new_protected = ""
                last_end = 0
                for match in ascii_pattern.finditer(protected):
                    start, end = match.span()
                    new_protected += protected[last_end:start]
                    
                    ph = f"__E{e_index}__"
                    e_index += 1
                    e_pmap[ph] = match.group(0)
                    new_protected += ph
                    
                    last_end = end
                new_protected += protected[last_end:]
                protected = new_protected

            # --- Glossary protection ---
            if self.glossary:
                protected, gloss_pmap = self.glossary.protect(protected, source_lang, target_lang)
                pmap.update(gloss_pmap)
                
            protected_texts.append(protected)
            placeholder_maps.append(pmap)
            ascii_maps.append(e_pmap)

        if not texts_to_translate:
            return

        # ---- Stage 2: Engine translate ----
        raw_results = engine_translate(protected_texts, self.config)

        # ---- Stage 3: Post-process + cache ----
        for raw_text, raw_result, pmap, e_pmap in zip(texts_to_translate, raw_results, placeholder_maps, ascii_maps):
            result = raw_result
            
            # 1. Restore ASCII placeholders first (in case they contain glossary elements, though we ran ASCII protection first)
            for ph, original in e_pmap.items():
                result = result.replace(ph, original)
                
            # 2. Restore glossary placeholders
            if self.glossary:
                result = self.glossary.restore(result, pmap)
                result = self.glossary.correct(result, source_lang, target_lang)
                
            # Store under the NORMALIZED key so minor OCR variations hit the same entry
            self._cache.put(self._normalize(raw_text), result)

    # ------------------------------------------------------------------
    # Synchronous translate (for user-typed input or one-off calls)
    # ------------------------------------------------------------------

    def translate(self, texts: list[str]) -> list[str]:
        """
        Blocking convenience wrapper: translate and return results immediately.
        Use for user-typed input where the caller needs the result synchronously.
        NOT called from the OCRWorker hot path.
        """
        missing = [t for t in texts if not self.is_cached(t)]
        if missing:
            self.translate_missing(missing)
        return [self._cache.get(self._normalize(t)) or t for t in texts]

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """
        Invalidate all cached translations.
        Call when glossary entries change — cached results may embed
        old term substitutions.
        """
        with self._lock:
            self._cache = LRUCache(3000)

    def set_glossary(self, glossary: GlossaryService | None) -> None:
        """Swap the glossary and invalidate the cache."""
        self.glossary = glossary
        self.clear_cache()
