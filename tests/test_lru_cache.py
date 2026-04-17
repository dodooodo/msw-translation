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
