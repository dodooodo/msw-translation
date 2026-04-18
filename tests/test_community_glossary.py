import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from community_glossary import (
    _parse_entries,
    fetch_glossary,
    fetch_index,
)


def _mock_urlopen(data: dict):
    """Returns a mock that behaves as urllib.request.urlopen used as a context manager."""
    body = json.dumps(data).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


# ── _parse_entries ────────────────────────────────────────────────────────────

class TestParseEntries:
    def test_valid_entries(self):
        data = {"entries": [
            {"terms": {"Korean": "안녕", "Traditional Chinese": "你好"}, "match_mode": "exact"},
            {"terms": {"Korean": "감사해요"}, "notes": "informal"},
        ]}
        entries = _parse_entries(data)
        assert len(entries) == 2
        assert entries[0].terms == {"Korean": "안녕", "Traditional Chinese": "你好"}
        assert entries[0].match_mode == "exact"
        assert entries[1].notes == "informal"

    def test_default_match_mode_is_exact(self):
        data = {"entries": [{"terms": {"Korean": "테스트"}}]}
        assert _parse_entries(data)[0].match_mode == "exact"

    def test_custom_match_mode_preserved(self):
        data = {"entries": [{"terms": {"Korean": "테스트"}, "match_mode": "prefix"}]}
        assert _parse_entries(data)[0].match_mode == "prefix"

    def test_skips_entries_with_empty_terms(self):
        data = {"entries": [
            {"terms": {}},
            {"terms": {"Korean": "안녕"}},
        ]}
        assert len(_parse_entries(data)) == 1

    def test_skips_entries_with_missing_terms_key(self):
        data = {"entries": [{"notes": "no terms key"}]}
        assert _parse_entries(data) == []

    def test_empty_entries_list(self):
        assert _parse_entries({"entries": []}) == []

    def test_missing_entries_key(self):
        assert _parse_entries({}) == []

    def test_partial_language_coverage(self):
        data = {"entries": [{"terms": {"Korean": "용사"}}]}
        entries = _parse_entries(data)
        assert "Traditional Chinese" not in entries[0].terms
        assert entries[0].terms["Korean"] == "용사"


# ── fetch_index ───────────────────────────────────────────────────────────────

class TestFetchIndex:
    def test_parses_glossary_list(self):
        payload = {"version": 3, "glossaries": [
            {"name": "MSW KR→ZH", "game": "MapleStory World",
             "languages": ["Korean", "Traditional Chinese"],
             "entry_count": 42, "raw_url": "https://example.com/g.json"},
        ]}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
            result = fetch_index()
        assert len(result) == 1
        g = result[0]
        assert g.name == "MSW KR→ZH"
        assert g.game == "MapleStory World"
        assert g.entry_count == 42
        assert g.raw_url == "https://example.com/g.json"
        assert "Korean" in g.languages

    def test_empty_glossaries_list(self):
        payload = {"version": 1, "glossaries": []}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
            assert fetch_index() == []

    def test_missing_glossaries_key(self):
        payload = {"version": 1}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
            assert fetch_index() == []

    def test_partial_glossary_fields_use_defaults(self):
        payload = {"glossaries": [{"name": "Partial"}]}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
            result = fetch_index()
        assert result[0].name == "Partial"
        assert result[0].entry_count == 0
        assert result[0].raw_url == ""
        assert result[0].game == ""

    def test_network_error_propagates(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with pytest.raises(urllib.error.URLError):
                fetch_index()


# ── fetch_glossary ────────────────────────────────────────────────────────────

class TestFetchGlossary:
    def test_parses_entries(self):
        payload = {"entries": [
            {"terms": {"Korean": "용사", "Traditional Chinese": "勇士"}}
        ]}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
            entries = fetch_glossary("https://example.com/g.json")
        assert len(entries) == 1
        assert entries[0].terms["Korean"] == "용사"

    def test_empty_entries(self):
        payload = {"entries": []}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
            assert fetch_glossary("https://example.com/g.json") == []

    def test_network_error_propagates(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")):
            with pytest.raises(urllib.error.URLError):
                fetch_glossary("https://example.com/g.json")
