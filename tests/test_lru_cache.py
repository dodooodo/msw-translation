"""Tests for LRUCache in translator_engine.py."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from translator_engine import LRUCache


def test_get_miss():
    c = LRUCache(10)
    assert c.get("missing") is None


def test_put_and_get():
    c = LRUCache(10)
    c.put("key", "value")
    assert c.get("key") == "value"


def test_len():
    c = LRUCache(10)
    assert len(c) == 0
    c.put("a", "1")
    assert len(c) == 1
    c.put("b", "2")
    assert len(c) == 2


def test_lru_eviction():
    """capacity=2: A then B then C → A evicted (least recently used)."""
    c = LRUCache(2)
    c.put("A", "a")
    c.put("B", "b")
    c.put("C", "c")        # A should be evicted
    assert c.get("A") is None
    assert c.get("B") == "b"
    assert c.get("C") == "c"
    assert len(c) == 2


def test_access_refreshes_order():
    """get() on A should move it to MRU position; next put evicts B, not A."""
    c = LRUCache(2)
    c.put("A", "a")
    c.put("B", "b")
    c.get("A")             # A is now most recently used
    c.put("C", "c")        # B should be evicted
    assert c.get("A") == "a"
    assert c.get("B") is None
    assert c.get("C") == "c"


def test_clear():
    c = LRUCache(10)
    c.put("x", "1")
    c.put("y", "2")
    c.clear()
    assert len(c) == 0
    assert c.get("x") is None
    assert c.get("y") is None


def test_overwrite_existing_key():
    c = LRUCache(10)
    c.put("k", "first")
    c.put("k", "second")
    assert c.get("k") == "second"
    assert len(c) == 1


def test_capacity_one():
    c = LRUCache(1)
    c.put("A", "a")
    c.put("B", "b")
    assert c.get("A") is None
    assert c.get("B") == "b"
    assert len(c) == 1


# ------------------------------------------------------------------
# Fuzzy cache lookup (1c — rapidfuzz-based similar-key fallback)
# ------------------------------------------------------------------

def test_get_or_similar_prefers_exact_match():
    c = LRUCache(10)
    c.put("hello world", "greeting")
    # Exact key is present — no fuzzy search needed.
    assert c.get_or_similar("hello world") == "greeting"


def test_get_or_similar_returns_value_for_jittered_key():
    """OCR jitter: one extra character shouldn't defeat the cache."""
    c = LRUCache(10)
    c.put("Hello, world!", "greeting")
    # Single-char insertion still ≥ 95% similar on fuzz.ratio.
    assert c.get_or_similar("Hello,  world!") == "greeting"


def test_get_or_similar_returns_none_when_nothing_close():
    c = LRUCache(10)
    c.put("apple pie", "v1")
    c.put("banana split", "v2")
    assert c.get_or_similar("quantum chromodynamics") is None


def test_get_or_similar_respects_threshold():
    c = LRUCache(10)
    c.put("abcdefghij", "value")
    # Very different key, high threshold → no match.
    assert c.get_or_similar("zzzzzzzzzz", threshold=95.0) is None


def test_get_or_similar_on_empty_cache_returns_none():
    c = LRUCache(10)
    assert c.get_or_similar("anything") is None


def test_get_or_similar_empty_key_returns_none():
    c = LRUCache(10)
    c.put("something", "value")
    assert c.get_or_similar("") is None


def test_get_or_similar_scan_limit_caps_work():
    """When scan_limit < cache size, only recent entries are searched."""
    c = LRUCache(100)
    # Old entry that would match if searched.
    c.put("target phrase", "old_value")
    # Fill with entries that are NOT close to "target phrase".
    for i in range(80):
        c.put(f"filler_{i}", f"val_{i}")
    # Jittered key so exact lookup misses, forcing the fuzzy scan.
    jittered = "target phrasee"  # 1-char addition, still ≥ 95% similar
    # scan_limit=10 only sees the last 10 fillers — no match.
    assert c.get_or_similar(jittered, scan_limit=10) is None
    # Large scan_limit walks far enough back to hit "target phrase".
    assert c.get_or_similar(jittered, scan_limit=200) == "old_value"


def test_get_or_similar_picks_best_of_multiple_candidates():
    c = LRUCache(10)
    c.put("hello world", "a")
    c.put("hello worlz", "b")        # 1-char diff
    c.put("totally different", "c")
    # Query is closer to "hello world" than "hello worlz".
    assert c.get_or_similar("hello world.") == "a"
