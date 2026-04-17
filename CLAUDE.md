# msw_translation — Claude Code Project Guide

## What this project is

Real-time game overlay translator for macOS, Windows, and Linux.
Captures a user-defined screen region, runs OCR, translates detected text, and
renders the translation as a transparent overlay — without blocking gameplay.

## Run

```bash
uv run main.py              # main overlay (entry point)
uv run translator.py        # also works (contains all UI classes; main.py imports from here)
uv run bbox_visualizer.py   # OCR debug visualiser (no translation)
```

## Project structure

```
main.py                 Entry point — imports AppController from translator.py
translator.py           Qt UI (SnippingToolWindow, TranslatorOverlay,
                        EditPopup, BBoxOverlay, ControlWindow, VisControl,
                        AppController) + OCRWorker + RawOCRWorker threads
bbox_visualizer.py      Thin wrapper — launches BBoxOnlyController (no translation)

ocr_model.py            OCRBlock dataclass — the single data type for the whole pipeline
block_merger.py         merge_blocks_by_proximity — pure Python, no platform deps
color_sampler.py        Pixel color sampling from CGImage — macOS only, no-op elsewhere
translator_engine.py    Thread-safe LRUCache + raw engine dispatch (Apple / Windows / Google / Dummy)
glossary_service.py     GlossaryEntry dataclass + CRUD + protect/restore/correct
translation_pipeline.py TranslationPipeline — pre-process → engine → post-process + cache
community_glossary.py   GlossaryMeta dataclass + fetch_index() / fetch_glossary() via urllib

capture/                Platform screenshot abstraction
  __init__.py             get_provider() factory
  base.py                 CaptureProvider ABC
  mac.py                  Quartz CGWindowListCreateImage (macOS)
  cross.py                mss-based fallback (Windows / Linux)

ocr/                    Platform OCR abstraction
  __init__.py             get_provider() factory + OCR_LANG_MAP constant
  base.py                 OCRProvider ABC
  mac.py                  Apple Vision VNRecognizeTextRequest (macOS)
  windows.py              Windows.Media.Ocr via winrt (Windows 10/11)
  tesseract.py            pytesseract fallback (Linux only)

config_manager.py       load_config() / save_config() — reads/writes config.json
settings_ui.py          PyQt6 settings dialog — QTabWidget: "⚙️ 一般" + "📖 詞彙表" tabs
translate_apple.swift   macOS 26+ Translation framework Swift CLI (stdin→stdout JSON)
translate_apple         Compiled Swift binary (auto-built on first Apple engine use)
translate_windows.cs    Windows 11 24H2+ Translation framework C# CLI (stdin→stdout JSON)
translate_windows.exe   Compiled C# binary (auto-built via dotnet on first Windows engine use)
translate_windows.csproj  .NET project for translate_windows.cs

translator.spec         PyInstaller build spec (onedir + BUNDLE for macOS; onefile for Win/Linux)
.github/workflows/
  release.yml           CI matrix build: macOS arm64 / Windows x64 / Linux x64 on v* tags

tests/                  pytest test suite (pure modules only — no Qt, no display needed)
  test_lru_cache.py       LRUCache eviction and access-order tests
  test_glossary_service.py  CRUD, protect/restore roundtrip, persistence
  test_translation_pipeline.py  Cache warmup, clear_cache, glossary integration
  test_block_merger.py    Merge conditions, threshold boundaries, bbox math

doc/                    Developer documentation
  architecture.md         Data flow, module responsibilities, design decisions
  adding_engine.md        How to add a new translation engine
  adding_platform.md      Platform support matrix and porting guide
  glossary.md             How the glossary pipeline works
```

## Key design rules

- **No Qt in pure modules.** `ocr_model`, `block_merger`, `color_sampler`,
  `translator_engine`, `glossary_service`, `translation_pipeline`, `community_glossary`,
  `capture/`, `ocr/` — none import PyQt6. Safe to test without a display.

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
  `ocr/mac.py`, and `color_sampler.py`. Windows-specific code lives in
  `ocr/windows.py` and `translate_windows.cs`. Swapping providers requires
  no changes to `translator.py`.

- **Config is a shared dict.** `AppController` creates one `config` dict and
  passes it by reference to `OCRWorker` and `TranslationPipeline`. Mutate it
  in-place with `config.update(load_config())` to propagate settings changes
  without restarting the worker.

- **PyInstaller bundles platform helper binaries.** `translator_engine._bundle_dir()`
  returns `sys._MEIPASS` when frozen, project root otherwise. Both `translate_apple`
  and `translate_windows.exe` are resolved through this path so they work inside
  the bundled `.app` / `.exe` without any changes to the subprocess call sites.

## Platform support matrix

| Feature | macOS | Windows 10/11 | Linux |
|---------|-------|---------------|-------|
| Screen capture | Quartz (`capture/mac.py`) | mss (`capture/cross.py`) | mss (`capture/cross.py`) |
| OCR | Apple Vision (`ocr/mac.py`) | Windows.Media.Ocr (`ocr/windows.py`) | Tesseract (`ocr/tesseract.py`) |
| Color sampling | ✅ (`color_sampler.py`) | — | — |
| Built-in translation | Apple (macOS 26+) | Windows (Win 11 24H2+) | — |
| Google Translate | ✅ | ✅ | ✅ |

## Config fields (`config.json`)

| Field | Default | Used by |
|-------|---------|---------|
| `source_language` | `"Korean"` | OCR language hints, translation engine source |
| `target_language` | `"Traditional Chinese"` | Translation engine target |
| `translator_engine` | `"dummy"` | `translator_engine.engine_translate` — `"apple"`, `"windows"`, `"google"`, or `"dummy"` |
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
uv run python -m pytest tests/ -v
```

All 50 tests cover the four pure modules and run in ~0.04 s with no display.
The `dummy` engine (returns originals) is used in pipeline tests — no API key or network needed.

## Building a release

```bash
# macOS: compile Swift helper first, then bundle
swiftc translate_apple.swift -o translate_apple
venv/bin/pyinstaller translator.spec
# → dist/MSW Translator.app
zip -r "MSW-Translator-vX.Y.Z-macos-arm64.zip" "dist/MSW Translator.app"

# Tag and release (triggers CI for all three platforms)
git tag vX.Y.Z && git push origin vX.Y.Z
```

GitHub Actions (`.github/workflows/release.yml`) runs a matrix build on macOS,
Windows, and Linux when a `v*` tag is pushed, producing three platform zips
automatically attached to the GitHub Release.

## Debugging

- **Wrong bbox positions or bad merges** → `uv run bbox_visualizer.py`
- **Wrong colors** → add `print` in `color_sampler._sample_block`, check `is_bgra` and `sx/sy`
- **Translation not updating** → check `pipeline._cache` length; confirm `missing_texts` is non-empty
- **Platform import errors** → check `sys.platform` value; macOS = `"darwin"`, Windows = `"win32"`
- **Windows OCR errors** → confirm `winrt-Windows.Media.Ocr` is installed; check language pack availability
- **Windows translation errors** → requires Win 11 24H2+; falls back to originals on older builds

## Settings UI (`settings_ui.py`)

`SettingsDialog(parent, glossary=None, pipeline=None)` — two tabs:

- **⚙️ 一般** — source/target language, engine (`apple` / `windows` / `google` / `dummy`),
  font size, text color, OCR interval
- **📖 詞彙表** — `QTableWidget` storing universal i18n entries mapping
  `[Traditional Chinese, Korean, English, 備註]` columns.
  Users can paste full multi-language tables from Excel. Edits completely overwrite
  active glossary entries using `GlossaryService.set_all_entries()`.
  On save, `pipeline.clear_cache()` is called if any entry was modified.

  Toolbar row above the table:
  - **☁ Community** — opens `CommunityGlossaryDialog`; fetches `index.json` from
    [dodooodo/msw-glossary](https://github.com/dodooodo/msw-glossary) in a `QThread`;
    lets user pick and import/merge a community glossary
  - **🔗 URL 匯入** — prompts for any raw JSON URL (Gist, GitHub, etc.);
    fetches and merges entries via `community_glossary.fetch_glossary_from_url()`
  - **↓ 匯出** — `QFileDialog` → saves current table to `glossary.json` format

`AppController` creates `GlossaryService` and `TranslationPipeline` and passes both
through `SnippingToolWindow` → `SettingsDialog`.

## Community glossary repo

`https://github.com/dodooodo/msw-glossary` — curated game-specific glossaries.

The app fetches `index.json` from this repo to populate the community browser.
Each entry in `index.json` declares `name`, `game`, `languages` (all 5 supported),
`entry_count`, and `raw_url` pointing to the actual glossary file.

Glossary files use the same format as local `glossary.json` (version 1, entries array
with `terms: {language: value}` dicts). Entries can have any subset of the 5 languages;
missing language keys are simply absent from `terms`.

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
