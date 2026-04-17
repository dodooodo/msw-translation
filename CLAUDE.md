# msw_translation — Claude Code Project Guide

## What this project is

Real-time game overlay translator for macOS (Windows/Linux cross-platform ready).
Captures a user-defined screen region, runs OCR, translates detected text, and
renders the translation as a transparent overlay — without blocking gameplay.

## Run

```bash
uv run translator.py        # main overlay
uv run bbox_visualizer.py   # OCR debug visualiser (no translation)
```

## Project structure

```
translator.py           Entry point + Qt UI (SnippingToolWindow, TranslatorOverlay,
                        EditPopup, BBoxOverlay, ControlWindow, VisControl,
                        AppController) + OCRWorker + RawOCRWorker threads
bbox_visualizer.py      Thin wrapper — launches BBoxOnlyController (no translation)

ocr_model.py            OCRBlock dataclass — the single data type for the whole pipeline
block_merger.py         merge_blocks_by_proximity — pure Python, no platform deps
color_sampler.py        Pixel color sampling from CGImage — macOS only, no-op elsewhere
translator_engine.py    Thread-safe LRUCache + raw engine dispatch (Apple / Google / Dummy)
glossary_service.py     GlossaryEntry dataclass + CRUD + protect/restore/correct
translation_pipeline.py TranslationPipeline — pre-process → engine → post-process + cache

capture/                Platform screenshot abstraction
  __init__.py             get_provider() factory
  base.py                 CaptureProvider ABC
  mac.py                  Quartz CGWindowListCreateImage (macOS)
  cross.py                mss-based fallback (Windows / Linux)

ocr/                    Platform OCR abstraction
  __init__.py             get_provider() factory + OCR_LANG_MAP constant
  base.py                 OCRProvider ABC
  mac.py                  Apple Vision VNRecognizeTextRequest (macOS)
  tesseract.py            pytesseract fallback (Windows / Linux)

config_manager.py       load_config() / save_config() — reads/writes config.json
settings_ui.py          PyQt6 settings dialog — QTabWidget: "⚙️ 一般" + "📖 詞彙表" tabs
translate_apple.swift   macOS 26+ Translation framework Swift CLI (stdin→stdout JSON)
translate_apple         Compiled Swift binary (auto-built on first Apple engine use)

tests/                  pytest test suite (pure modules only — no Qt, no display needed)
  test_lru_cache.py       LRUCache eviction and access-order tests
  test_glossary_service.py  CRUD, protect/restore roundtrip, persistence
  test_translation_pipeline.py  Cache warmup, clear_cache, glossary integration
  test_block_merger.py    Merge conditions, threshold boundaries, bbox math

doc/                    Developer documentation
  architecture.md         Data flow, module responsibilities, design decisions
  adding_engine.md        How to add a new translation engine
  adding_platform.md      How to port capture/OCR to a new platform
  glossary.md             How the glossary pipeline works
```

## Key design rules

- **No Qt in pure modules.** `ocr_model`, `block_merger`, `color_sampler`,
  `translator_engine`, `glossary_service`, `translation_pipeline`, `capture/`,
  `ocr/` — none import PyQt6. Safe to test without a display.

- **Non-blocking OCR loop with state tracking.** `OCRWorker.run()` never
  waits on an API call. Each tick classifies OCR blocks in priority order:
  (1) cache hit → emit immediately; (2) IoU > 0.8 + edit-distance < 2 match
  against `_tracked` → reuse existing translation without re-translating;
  (3) no match → enqueue for the single persistent consumer thread (drop-old
  strategy). Ghost rendering keeps blocks visible for `linger_frames` ticks
  after OCR misses, preventing flicker from brief detection failures.

- **Cache key = normalized OCR text.** `TranslationPipeline._normalize()` applies
  NFC unicode composition, whitespace collapse, and stray-character stripping before
  the cache lookup, so minor frame-to-frame OCR variations hit the same entry.
  Cached value = fully post-processed final result (glossary applied). O(1) hit for
  the ~95 % of frames that repeat. Call `pipeline.clear_cache()` when glossary entries change.

- **Platform isolation.** All macOS-specific code lives in `capture/mac.py`,
  `ocr/mac.py`, and `color_sampler.py`. Swapping in cross-platform providers
  requires no changes to `translator.py`.

- **Config is a shared dict.** `AppController` creates one `config` dict and
  passes it by reference to `OCRWorker` and `TranslationPipeline`. Mutate it
  in-place with `config.update(load_config())` to propagate settings changes
  without restarting the worker.

## Config fields (`config.json`)

| Field | Default | Used by |
|-------|---------|---------|
| `source_language` | `"Korean"` | OCR language hints, translation engine source |
| `target_language` | `"Traditional Chinese"` | Translation engine target |
| `translator_engine` | `"dummy"` | `translator_engine.engine_translate` |
| `font_size` | `26` | Reserved for future manual override; rendering uses bbox height |
| `text_color` | `"#FFE600"` | Reserved for future manual override; rendering samples pixels |
| `ocr_interval` | `1.0` | Seconds between OCR scans in `OCRWorker.run()` |
| `last_roi` | `[]` | Restored on next launch by `SnippingToolWindow` |
| `min_confidence` | `0.0` | Drop Vision OCR blocks below this confidence (0 = off) |
| `min_text_length` | `1` | Drop blocks shorter than N characters (1 = off) |
| `linger_frames` | `3` | Ticks to ghost-render a block after OCR miss (3 × 0.2 s ≈ 0.6 s) |
| `merge_max_height_ratio` | `1.2` | Max row-height ratio to consider two blocks the same font size (`block_merger`) |
| `merge_gap_ratio` | `0.8` | Vertical gap must be < avg\_height × this value to merge (`block_merger`) |
| `merge_min_h_overlap` | `0.3` | Horizontal overlap must be ≥ this fraction of the narrower block's width (`block_merger`) |

## Running tests

```bash
python -m pytest tests/ -v
```

All 50 tests cover the four pure modules and run in ~0.04 s with no display.
The `dummy` engine (returns originals) is used in pipeline tests — no API key or network needed.

## Debugging

- **Wrong bbox positions or bad merges** → `uv run bbox_visualizer.py`
- **Wrong colors** → add `print` in `color_sampler._sample_block`, check `is_bgra` and `sx/sy`
- **Translation not updating** → check `pipeline._cache` length; confirm `missing_texts` is non-empty
- **Platform import errors** → confirm `sys.platform == "darwin"` before using Quartz/Vision

## Settings UI (`settings_ui.py`)

`SettingsDialog(parent, glossary=None, pipeline=None)` — two tabs:

- **⚙️ 一般** — source/target language, engine, font size, text color, OCR interval
- **📖 詞彙表** — `QTableWidget` storing universal i18n entries mapping `[Traditional Chinese, Korean, English]`.
  Users can paste full multi-language tables from Excel. Edits completely overwrite active glossary entries using `GlossaryService.set_all_entries()`.
  On save, `pipeline.clear_cache()` is called if any entry was modified.

`AppController` creates `GlossaryService` and `TranslationPipeline` and passes both
through `SnippingToolWindow` → `SettingsDialog`.

## User input panel (`ControlWindow`)

`ControlWindow` has a second row: `QLineEdit` + "翻譯" button.
Both paths below display the result in the same pill row (`_result_row`): clickable
`[input] → [translated]` pills; clicking either copies the text to the clipboard.

**Engine translation** — user types text (target language) and presses Enter or "翻譯":
`_on_submit()` calls `engine_translate` directly with the config reversed
(target → source), applies glossary protect/restore, then fills the pills.

**Glossary lookup** — user types a prefix and clicks an autocomplete suggestion:
`_on_suggestion_clicked()` fills the pills directly from the glossary entry (no engine call).

`AppController` passes `pipeline` to `ControlWindow` so `_on_submit` can access
the config and glossary for the reverse translation.

## Future work (already architected for)

- **Packaging** — entry point is `if __name__ == "__main__"` in `translator.py`; isolate into `main.py` before PyInstaller bundling
