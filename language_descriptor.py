"""language_descriptor.py

Per-language metadata: BCP-47 code, OCR hints, and text-processing flags.

Single source of truth that replaces string-branching on config["source_language"]
/ config["target_language"] in the rest of the codebase.

Ported from Translumo's
src/Translumo.Infrastructure/Language/LanguageDescriptor.cs (Apache 2.0).
Only the fields msw_translation actually needs today are kept.

Pure Python, no Qt, no platform deps — safe to import anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageDescriptor:
    """Metadata for a single language.

    display_name is the key shipped in config.json ("Korean", "Traditional Chinese", …).
    Keeping the display name as the primary key preserves the human-readable config
    format that all existing call sites already rely on.
    """
    display_name: str
    code: str                       # BCP-47, e.g. "ko-KR"
    asian: bool
    use_end_punctuation: bool       # add trailing period if missing (European langs)
    use_word_tokenizer: bool        # language has no spaces between words (CJK)
    use_space_remover: bool         # collapse all whitespace to empty (CJK)
    ocr_languages: tuple[str, ...]  # hints passed to OCRProvider.recognize
    validity_model: str | None = None  # reserved for future ONNX text-score model


LANGUAGES: dict[str, LanguageDescriptor] = {
    "Korean": LanguageDescriptor(
        display_name="Korean",
        code="ko-KR",
        asian=True,
        use_end_punctuation=False,
        use_word_tokenizer=True,
        use_space_remover=False,     # Korean uses spaces between eojeols
        ocr_languages=("ko-KR",),
        validity_model="kor",
    ),
    "Japanese": LanguageDescriptor(
        display_name="Japanese",
        code="ja-JP",
        asian=True,
        use_end_punctuation=False,
        use_word_tokenizer=True,
        use_space_remover=True,
        ocr_languages=("ja-JP",),
        validity_model="jap",
    ),
    "English": LanguageDescriptor(
        display_name="English",
        code="en-US",
        asian=False,
        use_end_punctuation=True,
        use_word_tokenizer=False,
        use_space_remover=False,
        ocr_languages=("en-US",),
        validity_model="eng",
    ),
    "Traditional Chinese": LanguageDescriptor(
        display_name="Traditional Chinese",
        code="zh-TW",
        asian=True,
        use_end_punctuation=False,
        use_word_tokenizer=True,
        use_space_remover=True,
        ocr_languages=("zh-Hant",),
        validity_model="chi",
    ),
    "Simplified Chinese": LanguageDescriptor(
        display_name="Simplified Chinese",
        code="zh-CN",
        asian=True,
        use_end_punctuation=False,
        use_word_tokenizer=True,
        use_space_remover=True,
        ocr_languages=("zh-Hans",),
        validity_model="chi",
    ),
}


def get(display_name: str) -> LanguageDescriptor:
    """Return the descriptor for `display_name`, falling back to Korean.

    Korean is the default source language in DEFAULT_CONFIG, so using it as
    the fallback keeps behaviour consistent when an unknown name sneaks in
    (older configs, typos in tests, etc.).
    """
    return LANGUAGES.get(display_name, LANGUAGES["Korean"])
