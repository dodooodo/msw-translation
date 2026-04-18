"""
translator_engine.py
LRU translation cache + raw engine dispatch (Apple / Windows / Google / Dummy).
Pure Python — no Qt, no Quartz, no platform dependencies.

This module handles the mechanical work of calling translation APIs.
It knows nothing about glossaries, caching strategy, or pipeline ordering —
those belong in translation_pipeline.py.

Performance
-----------
Apple and Windows built-in engines use long-running daemon subprocesses.
The helper binary is spawned once per (source, target) language pair and kept
alive for the lifetime of the application.  Subsequent translate calls write a
JSON line to the daemon's stdin and read a JSON line from stdout, eliminating
the ~100-300 ms process-startup overhead that the old one-shot approach paid on
every cache miss.
"""
from __future__ import annotations

import atexit
import json
import threading
import os
import sys
import subprocess
from collections import OrderedDict

from rapidfuzz import fuzz, process

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

    def get_or_similar(
        self,
        key: str,
        threshold: float = 95.0,
        scan_limit: int = 64,
    ) -> str | None:
        """Exact lookup first; on miss, scan the most recently used
        ``scan_limit`` keys with ``rapidfuzz.fuzz.ratio`` and return the value
        whose key is closest above ``threshold`` (0–100 scale).

        Returns ``None`` if nothing is similar enough.  The caller can write
        the fuzzy-matched value back under the current key via ``put()`` to
        turn future lookups into O(1) exact hits.

        Fuzzy scan does not move the matched key to MRU position — we can't
        tell which side of the OCR jitter is 'canonical', and ``put()`` will
        refresh order on the next write.
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            # Snapshot the MRU end of the ordered dict for the fuzzy scan.
            # OrderedDict iteration is insertion order (LRU → MRU), so the
            # last `scan_limit` entries are the most recently used.
            recent = list(self._cache.items())[-scan_limit:]

        if not recent or not key:
            return None

        keys = [k for k, _ in recent]
        best = process.extractOne(
            key, keys, scorer=fuzz.ratio, score_cutoff=threshold
        )
        if best is None:
            return None
        _, _score, idx = best
        return recent[idx][1]

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
# Translation Daemon — long-running subprocess IPC
# ---------------------------------------------------------------------------

class TranslationDaemon:
    """Manages a long-running helper binary that reads JSON lines on stdin
    and writes JSON result lines on stdout.

    Thread-safe: a lock serialises all translate() calls so exactly one
    request is in-flight at a time.
    """

    def __init__(self, binary: str, source: str, target: str, label: str):
        self._binary = binary
        self._source = source
        self._target = target
        self._label  = label      # for log messages, e.g. "Apple翻譯"
        self._lock   = threading.Lock()
        self._proc:  subprocess.Popen | None = None
        # Register for process cleanup on interpreter shutdown
        atexit.register(self.stop)

    def _start(self) -> subprocess.Popen:
        """Spawn (or respawn) the daemon process."""
        proc = subprocess.Popen(
            [self._binary, self._source, self._target],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,           # line-buffered
        )
        self._proc = proc
        return proc

    def _ensure_running(self) -> subprocess.Popen | None:
        """Return the running process, spawning it if necessary."""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        # Process died or never started — (re)spawn
        try:
            return self._start()
        except Exception as e:
            print(f"[{self._label}] 無法啟動 daemon: {e}")
            return None

    def translate(self, texts: list[str]) -> list[str]:
        """Send a batch of texts and return translated results.
        Falls back to returning originals on any error."""
        with self._lock:
            proc = self._ensure_running()
            if proc is None:
                return texts
            payload = json.dumps({"texts": texts}, ensure_ascii=False)
            try:
                proc.stdin.write(payload + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                if not line:
                    # Process died mid-flight — try once more
                    print(f"[{self._label}] daemon 意外關閉，重新啟動…")
                    self._proc = None
                    proc = self._ensure_running()
                    if proc is None:
                        return texts
                    proc.stdin.write(payload + "\n")
                    proc.stdin.flush()
                    line = proc.stdout.readline()
                    if not line:
                        return texts
                return json.loads(line)
            except Exception as e:
                print(f"[{self._label}] daemon 通訊錯誤: {e}")
                # Kill broken process so next call respawns
                self._kill()
                return texts

    def stop(self) -> None:
        """Terminate the daemon process."""
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Apple Translation (macOS 26+)
# ---------------------------------------------------------------------------

def _bundle_dir() -> str:
    """Return the directory containing platform helper binaries.
    Inside a PyInstaller bundle this is sys._MEIPASS; otherwise the module dir."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(__file__))


_APPLE_BINARY_PATH = os.path.join(_bundle_dir(), "translate_apple")
_APPLE_SWIFT_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_apple.swift")

_APPLE_LANG_MAP: dict[str, str] = {
    "Korean":             "ko",
    "Japanese":           "ja",
    "English":            "en",
    "Traditional Chinese":"zh-Hant",
    "Simplified Chinese": "zh-Hans",
}

# Keyed by (source_code, target_code) → TranslationDaemon
_apple_daemons: dict[tuple[str, str], TranslationDaemon] = {}
_apple_daemons_lock = threading.Lock()


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


def _get_apple_daemon(source: str, target: str) -> TranslationDaemon | None:
    """Return (or create) the Apple daemon for the given language pair."""
    key = (source, target)
    with _apple_daemons_lock:
        if key in _apple_daemons:
            return _apple_daemons[key]
        binary = _ensure_apple_binary()
        if not binary:
            return None
        daemon = TranslationDaemon(binary, source, target, "Apple翻譯")
        _apple_daemons[key] = daemon
        return daemon


def _translate_apple(texts: list[str], source_lang: str, target_lang: str) -> list[str]:
    source = _APPLE_LANG_MAP.get(source_lang, "en")
    target = _APPLE_LANG_MAP.get(target_lang, "zh-Hant")
    daemon = _get_apple_daemon(source, target)
    if daemon is None:
        return texts
    return daemon.translate(texts)


# ---------------------------------------------------------------------------
# Windows built-in translation (Windows 11 24H2+)
# ---------------------------------------------------------------------------

_WINDOWS_BINARY_PATH = os.path.join(_bundle_dir(), "translate_windows.exe")
_WINDOWS_CS_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_windows.cs")
_WINDOWS_CSPROJ_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_windows.csproj")

_WINDOWS_LANG_MAP: dict[str, str] = {
    "Korean":             "ko",
    "Japanese":           "ja",
    "English":            "en",
    "Traditional Chinese":"zh-Hant",
    "Simplified Chinese": "zh-Hans",
}

# Keyed by (source_code, target_code) → TranslationDaemon
_windows_daemons: dict[tuple[str, str], TranslationDaemon] = {}
_windows_daemons_lock = threading.Lock()


def _ensure_windows_binary() -> str | None:
    if os.path.exists(_WINDOWS_BINARY_PATH):
        return _WINDOWS_BINARY_PATH
    if not os.path.exists(_WINDOWS_CSPROJ_PATH):
        print("[Windows翻譯] 找不到 translate_windows.csproj")
        return None
    print("[Windows翻譯] 首次使用，正在編譯翻譯器…")
    result = subprocess.run(
        ["dotnet", "publish", _WINDOWS_CSPROJ_PATH,
         "-r", "win-x64", "-o", os.path.dirname(_WINDOWS_BINARY_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[Windows翻譯] 編譯失敗:\n{result.stderr}")
        return None
    print("[Windows翻譯] 編譯完成！")
    return _WINDOWS_BINARY_PATH


def _get_windows_daemon(source: str, target: str) -> TranslationDaemon | None:
    """Return (or create) the Windows daemon for the given language pair."""
    key = (source, target)
    with _windows_daemons_lock:
        if key in _windows_daemons:
            return _windows_daemons[key]
        binary = _ensure_windows_binary()
        if not binary:
            return None
        daemon = TranslationDaemon(binary, source, target, "Windows翻譯")
        _windows_daemons[key] = daemon
        return daemon


def _translate_windows(texts: list[str], source_lang: str, target_lang: str) -> list[str]:
    source = _WINDOWS_LANG_MAP.get(source_lang, "ko")
    target = _WINDOWS_LANG_MAP.get(target_lang, "zh-Hant")
    daemon = _get_windows_daemon(source, target)
    if daemon is None:
        return texts
    return daemon.translate(texts)


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
    if engine == "windows":
        return _translate_windows(texts, source_lang, target_lang)
    if engine == "google":
        return _translate_google(texts, source_lang, target_lang)

    # Dummy engine — return originals (useful for layout/alignment testing)
    return texts
