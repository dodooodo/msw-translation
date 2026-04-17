"""community_glossary.py — Fetch community glossaries from the msw-glossary GitHub repo.

Pure stdlib: no third-party deps (uses urllib.request).
All network calls run in a QThread — never call fetch_* from the Qt main thread.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from glossary_service import GlossaryEntry

COMMUNITY_INDEX_URL = (
    "https://raw.githubusercontent.com/dodooodo/msw-glossary/main/index.json"
)

_TIMEOUT = 8  # seconds


@dataclass
class GlossaryMeta:
    name: str
    game: str
    languages: list[str]   # all languages covered, e.g. ["Korean", "Traditional Chinese"]
    entry_count: int
    raw_url: str


def fetch_index() -> list[GlossaryMeta]:
    """Download and parse the community glossary index.
    Raises urllib.error.URLError or ValueError on network/parse failure."""
    with urllib.request.urlopen(COMMUNITY_INDEX_URL, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [
        GlossaryMeta(
            name=g.get("name", ""),
            game=g.get("game", ""),
            languages=g.get("languages", []),
            entry_count=g.get("entry_count", 0),
            raw_url=g.get("raw_url", ""),
        )
        for g in data.get("glossaries", [])
    ]


def fetch_glossary(raw_url: str) -> list[GlossaryEntry]:
    """Download a glossary JSON file and return its entries.
    Raises urllib.error.URLError or ValueError on network/parse failure."""
    with urllib.request.urlopen(raw_url, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _parse_entries(data)


def fetch_glossary_from_url(url: str) -> list[GlossaryEntry]:
    """Fetch and parse a glossary from any raw URL (Gist, GitHub, etc.)."""
    return fetch_glossary(url)


def _parse_entries(data: dict) -> list[GlossaryEntry]:
    entries = []
    for e in data.get("entries", []):
        terms = e.get("terms", {})
        if not terms:
            continue
        entries.append(GlossaryEntry(
            terms=terms,
            match_mode=e.get("match_mode", "exact"),
            notes=e.get("notes", ""),
        ))
    return entries
