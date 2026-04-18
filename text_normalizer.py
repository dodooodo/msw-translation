"""text_normalizer.py

CJK-aware OCR text normalisation.

Different OCR engines spell the same glyph differently — Apple Vision returns
the full-width comma ``，`` (U+FF0C) while Windows OCR returns ``,`` (U+002C),
and Tesseract sometimes produces ``ー`` (KATAKANA-HIRAGANA PROLONGED SOUND MARK)
where others produce ``-``.  Those differences silently defeat the
TranslationPipeline cache (two keys for the same scene) and confuse downstream
translation engines.

``normalize_ocr_text`` swaps 36 common CJK punctuation glyphs and full-width
digits for ASCII equivalents, collapses whitespace, trims stray edge
characters, and optionally applies language-specific rules.  Designed to be
called on cache keys only — the raw text is still what gets sent to the
translation engine.

Ported from Translumo's
``src/Translumo.Processing/TextProcessing/TextValidityPredictor.cs`` (Apache 2.0,
the ``_replacers`` table at lines 40-79 and ``PreProcessText`` at lines 149-177).

Pure Python — no Qt, no platform deps.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 29-entry CJK punctuation / digit table (port of Translumo ``_replacers``).
# Order matters: multi-char keys are applied first so ``・・・`` → ``...`` wins
# over a per-char pass on ``・``.
# ---------------------------------------------------------------------------

CJK_PUNCT_MAP: dict[str, str] = {
    # Multi-character sequences first
    "・・・": "...",
    " 、":  ",",

    # Punctuation
    "，":  ",",
    "！":  "!",
    "？":  "?",
    "；":  ";",
    "：":  ":",
    "（":  "(",
    "）":  ")",
    "［":  "[",
    "］":  "]",
    "【":  "[",
    "】":  "]",
    "、":  ",",
    "…":   "...",
    "⸺":   "-",
    "．":   ". ",
    "♪":   "",
    "〟":   '"',
    "〝":   '"',
    "\u201d": '"',   # U+201D right double quotation mark
    "\u201c": '"',   # U+201C left double quotation mark
    "‥":    "..",
    "`":    "'",
    "—":    "-",
    "′":    "'",

    # Full-width Arabic digits
    "０": "0",
    "１": "1",
    "２": "2",
    "３": "3",
    "４": "4",
    "５": "5",
    "６": "6",
    "７": "7",
    "８": "8",
    "９": "9",
}


_MULTI_WS      = re.compile(r"\s+")
_DOT_AT_EDGES  = re.compile(r"^\.+|\.+$")
_SENTENCE_ENDS = set(".,;:!?。、！？；：")  # terminal punctuation that blocks auto-dot


def normalize_ocr_text(
    text: str,
    *,
    is_asian: bool = False,                 # noqa: ARG001 — reserved for 1c
    use_end_punctuation: bool = True,
    use_space_remover: bool = False,
) -> str:
    """Clean one line of OCR output for use as a cache key.

    Parameters
    ----------
    text
        Raw OCR string, already NFC-normalised by the caller if desired.
    is_asian
        Reserved — currently unused here, but consumed by the fuzzy-cache
        threshold selection (see phase 1c) so keeping the parameter stable
        avoids churn in call sites when 1c lands.
    use_end_punctuation
        European languages that want a trailing period if missing
        (mirrors ``LanguageDescriptor.use_end_punctuation``).
    use_space_remover
        CJK languages where whitespace carries no meaning — collapse to zero
        so ``"こんにちは 世界"`` and ``"こんにちは世界"`` hit the same entry.
        Safe for cache keys; never apply to text shown to the engine or user.
    """
    # 1. Character / sequence swaps (CJK punct → ASCII).
    for k, v in CJK_PUNCT_MAP.items():
        if k in text:
            text = text.replace(k, v)

    # 2. Trim stray dashes / spaces at the edges.
    text = text.strip("- ")

    # 3. Strip a single pair of matching leading/trailing quotes.
    if len(text) > 1 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1]

    # 4. Strip runs of leading or trailing dots.
    text = _DOT_AT_EDGES.sub("", text)

    # 5. Collapse internal whitespace.
    text = _MULTI_WS.sub(" ", text).strip()

    # 6. Optional trailing period for European languages.
    if use_end_punctuation and text and text[-1] not in _SENTENCE_ENDS:
        text += "."

    # 7. Optional full space removal (CJK cache keys only).
    if use_space_remover:
        text = text.replace(" ", "")

    return text
