# Glossary Pipeline

## Purpose

Game UI contains proper nouns — item names, skill names, NPC names — that
general-purpose translation engines translate incorrectly or inconsistently.
The glossary lets users pin specific term translations so they are never
altered by the engine.

Example: `스타포스` (StarForce) should always become `星之力`, but Google and
Apple may produce `星力`, `星强化`, or `星の力` depending on context.

## How it fits in the pipeline

```
Raw OCR text
    │
    ▼ glossary.protect()          ← Pre-processing
Protected text  (e.g. "캐릭터 __T0__ 강화")
    │
    ▼ engine_translate()
Raw translated  (e.g. "角色 __T0__ 強化")
    │
    ▼ glossary.restore()          ← Post-processing: restore placeholders
    ▼ glossary.correct()          ← Post-processing: fix any that slipped through
Final result    (e.g. "角色 星之力 強化")
    │
    ▼ pipeline._cache.put(raw_text, final_result)
```

## protect()

Scans the source text for all glossary entries that match the active
language pair. Replaces each match with a numbered placeholder.

```python
text, pmap = glossary.protect("캐릭터 스타포스 강화", "Korean", "Traditional Chinese")
# text = "캐릭터 __T0__ 강화"
# pmap = {"__T0__": "星之力"}
```

Placeholder format: `__T{n}__`. Underscores survive most translation engines
intact because the engines treat them as punctuation rather than words.

Patterns are compiled dynamically via `re.compile(re.escape(term))`. For 50 entries and 10 text blocks at 10 fps, overhead remains safely beneath ~500 µs via Python's internal Regex compile caching mechanisms.

### Fuzzy fallback (Pass 2)

After the exact regex pass, any glossary entries that did **not** match are
retried with a fuzzy substring search. This handles OCR character confusion
(e.g. Korean `무`↔`우`, `얼`↔`멀`) that would otherwise bypass glossary
protection entirely.

The fuzzy pass uses a **sliding window** over the text and **Levenshtein edit
distance** (`rapidfuzz.distance.Levenshtein`) as the similarity metric.
Tolerance is expressed as an absolute character-error budget controlled by
three config fields:

| Config field | Default | Description |
|---|---|---|
| `fuzzy_length_threshold` | `3` | Terms ≤ this many chars (space-stripped) use the short budget |
| `fuzzy_short_max_distance` | `1` | Max OCR errors allowed for short terms |
| `fuzzy_long_max_distance` | `2` | Max OCR errors allowed for long terms |

Set either distance to `0` to disable fuzzy matching for that class of terms.

Safety guards:
- **Min term length = 2** — single-char terms are excluded (too many false positives).
- **Min window size = 2** — prevents 1-char windows from producing spurious high scores.
- **Placeholder contamination guard** — windows containing `__` (the shared marker for
  `__T0__`, `__E0__` etc.) are skipped so Pass 1 substitutions cannot cause spurious
  fuzzy matches in Pass 2.
- **Spaces are stripped** before comparison so `"듀얼 보우건"` and `"듀얼보우건"` are equivalent.

**Why Levenshtein distance instead of a ratio?**
A ratio-based threshold (e.g. 75%) degrades for medium-length terms: a 5-char term
with 2 errors scores only 60%, which would be rejected. Absolute edit distance
grants a fixed error budget regardless of term length.

Examples:
```python
g.add_entry(GlossaryEntry(terms={"Korean": "듀얼 보우건", "Traditional Chinese": "雙弩槍"}))

# 1 OCR error (우→무) — distance 1 ≤ long_max_distance(2) → matched
text, pmap = g.protect("듀얼 보무건", "Korean", "Traditional Chinese")
# text = "__T0__"   pmap = {"__T0__": "雙弩槍"}

# 2 OCR errors (얼→멀, 우→무) — distance 2 ≤ long_max_distance(2) → matched
text, pmap = g.protect("듀멀 보무건", "Korean", "Traditional Chinese")
# text = "__T0__"   pmap = {"__T0__": "雙弩槍"}

# 3 OCR errors — distance 3 > long_max_distance(2) → rejected (safe)
```

## restore()

After translation, replaces each placeholder with its target term using
simple `str.replace()`.

```python
result = glossary.restore("角色 __T0__ 強化", {"__T0__": "星之力"})
# result = "角色 星之力 強化"
```

## correct()

Fallback pass. Some engines rewrite or split placeholders. `correct()` does
a direct string replacement of any known incorrect translations in the output.

Currently a no-op for entries already correctly restored — only acts when
the placeholder was lost. This pass is intentionally conservative.

## Cache interaction

Cache key = **raw OCR text** (before `protect()`).
Cache value = **final result** (after `restore()` + `correct()`).

This means:
- Cache hits skip the entire glossary pipeline — O(1), zero overhead.
- Cache misses run the full pipeline once; the result is cached forever for
  that exact raw text.
- When glossary entries change, call `pipeline.clear_cache()` to invalidate
  stale results that embedded old term translations.

## Storage format (`glossary.json`)

```json
{
  "version": 1,
  "entries": [
    {
      "terms": {
        "Korean": "스타포스",
        "Traditional Chinese": "星之力"
      },
      "match_mode": "exact",
      "notes": "StarForce enhancement system"
    }
  ]
}
```

`match_mode` values:
- `"exact"` — matches the literal string (case-sensitive for CJK/Korean)
- `"contains"` — same as exact currently; reserved for future substring matching
- Regex support is planned for a future iteration

Regardless of `match_mode`, all entries that fail the exact regex pass are
automatically retried with the fuzzy fallback (see [Fuzzy fallback](#fuzzy-fallback-pass-2) above).

## CRUD API

```python
from glossary_service import GlossaryService, GlossaryEntry

g = GlossaryService()   # loads glossary.json automatically

g.add_entry(GlossaryEntry(
    terms={
        "Korean": "스타포스",
        "Traditional Chinese": "星之力"
    }
))

entries = g.get_entries("Korean", "Traditional Chinese")

g.remove_entry_by_term("스타포스", "Korean")
```

`add_entry` appends the entry. Use `set_all_entries` for bulk resetting from UI.
All mutations call `save()` automatically.

## Glossary settings UI

The glossary tab is implemented in `settings_ui.py` (`SettingsDialog`, "📖 詞彙表" tab).

**How it works:**
- On open: loads all stored entries into a multi-language `QTableWidget` 
  (`[繁中, 韓文, 英文, 備註]` columns).
- **Add row** (➕): appends a blank inline-editable row.
- **Remove row** (🗑️): removes the selected row from the table.
- **Paste (Ctrl+V)**: Users can directly paste multi-column data from Excel or Google Sheets. The table will parse horizontal rows mapping naturally into internal language terms.
- On **Save**: rebuilds dictionary entries mapping translations to active language keys.
  - Safely overwrites backend memory via `glossary.set_all_entries()`
  - Calls `pipeline.clear_cache()` clearing invalidated texts currently on-screen.

The unified table allows editing all language variants of a term simultaneously without needing to manually toggle source and target language fields first.

## Community glossary sharing

Three sharing mechanisms are exposed in the 詞彙表 toolbar:

### ☁ Community Glossaries

Fetches `index.json` from [dodooodo/msw-glossary](https://github.com/dodooodo/msw-glossary)
in a background `QThread` and shows a list of available glossaries. Selecting one fetches
the raw JSON and offers a **Replace** / **Merge** choice before importing.

### 🔗 URL 匯入

Prompts for any raw JSON URL (GitHub Gist, raw GitHub file, etc.) and imports it the same
way as community glossaries. Users share URLs on Discord, Reddit, or other channels.

### ↓ 匯出

Saves the current table to a `glossary.json`-format file on disk. The exported file is
directly importable by any instance of the app via URL 匯入 or as a PR to the community repo.

## Community repo format (`index.json`)

```json
{
  "version": 1,
  "glossaries": [
    {
      "name": "MapleStory Worlds — General",
      "game": "MapleStory Worlds",
      "languages": ["Korean", "Japanese", "English", "Traditional Chinese", "Simplified Chinese"],
      "entry_count": 6,
      "author": "dodooodo",
      "raw_url": "https://raw.githubusercontent.com/dodooodo/msw-glossary/main/glossaries/maplestory-worlds/kr-zh-hant.json"
    }
  ]
}
```

`languages` lists all languages the file declares support for. Individual entries may
omit language keys that are not yet filled in — the app uses whatever is present in `terms`.
