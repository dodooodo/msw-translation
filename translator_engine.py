"""
translator_engine.py
LRU translation cache + raw engine dispatch (Apple / Google / Dummy).
Pure Python — no Qt, no Quartz, no platform dependencies.

This module handles the mechanical work of calling translation APIs.
It knows nothing about glossaries, caching strategy, or pipeline ordering —
those belong in translation_pipeline.py.
"""
from __future__ import annotations

import json
import threading
import os
import subprocess
from collections import OrderedDict

# ---------------------------------------------------------------------------
# LRU Cache
# ---------------------------------------------------------------------------

class LRUCache:
    """Thread-safe LRU cache.
    get() and put() are guarded by a lock so concurrent access from the
    OCR worker loop and background translation threads cannot corrupt the
    internal OrderedDict state."""

    def __init__(self, capacity: int = 2000):
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.capacity = capacity

    def get(self, key: str) -> str | None:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self.capacity:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


# ---------------------------------------------------------------------------
# Apple Translation (macOS 26+)
# ---------------------------------------------------------------------------

_APPLE_BINARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_apple")
_APPLE_SWIFT_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_apple.swift")

_APPLE_LANG_MAP: dict[str, str] = {
    "Korean":             "ko",
    "Japanese":           "ja",
    "English":            "en",
    "Traditional Chinese":"zh-Hant",
    "Simplified Chinese": "zh-Hans",
}


def _ensure_apple_binary() -> str | None:
    if os.path.exists(_APPLE_BINARY_PATH):
        return _APPLE_BINARY_PATH
    if not os.path.exists(_APPLE_SWIFT_PATH):
        print("[Apple翻譯] 找不到 translate_apple.swift")
        return None
    print("[Apple翻譯] 首次使用，正在編譯 Swift 翻譯器…")
    result = subprocess.run(
        ["swiftc", _APPLE_SWIFT_PATH, "-o", _APPLE_BINARY_PATH],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[Apple翻譯] 編譯失敗:\n{result.stderr}")
        return None
    print("[Apple翻譯] 編譯完成！")
    return _APPLE_BINARY_PATH


def _translate_apple(texts: list[str], source_lang: str, target_lang: str) -> list[str]:
    source  = _APPLE_LANG_MAP.get(source_lang, "en")
    target  = _APPLE_LANG_MAP.get(target_lang, "zh-Hant")
    binary  = _ensure_apple_binary()
    if not binary:
        return texts  # fallback: return originals

    payload = json.dumps({"texts": texts, "source": source, "target": target},
                         ensure_ascii=False)
    try:
        result = subprocess.run([binary], input=payload, capture_output=True,
                                text=True, timeout=30)
        if result.returncode != 0:
            print(f"[Apple翻譯] 錯誤: {result.stderr.strip()}")
            return texts
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print("[Apple翻譯] 超時")
        return texts
    except Exception as e:
        print(f"[Apple翻譯] 例外: {e}")
        return texts


# ---------------------------------------------------------------------------
# Google Translate
# ---------------------------------------------------------------------------

_GOOGLE_LANG_MAP: dict[str, str] = {
    "Traditional Chinese": "zh-tw",
    "Simplified Chinese":  "zh-cn",
    "English":             "en",
    "Korean":              "ko",
    "Japanese":            "ja",
}


def _translate_google(texts: list[str], source_lang: str, target_lang: str) -> list[str]:
    try:
        from googletrans import Translator
        translator = Translator()
        dest    = _GOOGLE_LANG_MAP.get(target_lang, "zh-tw")
        results = translator.translate(texts, dest=dest)
        if isinstance(results, list):
            return [r.text for r in results]
        return [results.text]
    except ImportError:
        print("[Google翻譯] 未安裝 googletrans==4.0.0-rc1")
        return texts
    except Exception as e:
        print(f"[Google翻譯] 錯誤: {e}")
        return texts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def engine_translate(texts: list[str], config: dict) -> list[str]:
    """
    Raw engine dispatch — no cache, no glossary, no pipeline logic.
    Returns translations in the same order as `texts`.
    Falls back to returning originals on any error.
    """
    if not texts:
        return []

    engine      = config.get("translator_engine", "dummy")
    source_lang = config.get("source_language",  "Korean")
    target_lang = config.get("target_language",  "Traditional Chinese")

    if engine == "apple":
        return _translate_apple(texts, source_lang, target_lang)
    if engine == "google":
        return _translate_google(texts, source_lang, target_lang)

    # Dummy engine — return originals (useful for layout/alignment testing)
    return texts
