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
translator_engine.py    Thread-safe LRUCache (+ fuzzy get_or_similar) + raw engine dispatch
glossary_service.py     GlossaryEntry dataclass + CRUD + protect/restore/correct + fuzzy fallback
translation_pipeline.py TranslationPipeline — pre-process → engine → post-process + cache
community_glossary.py   GlossaryMeta dataclass + fetch_index() / fetch_glossary() via urllib
language_descriptor.py  LanguageDescriptor dataclass — per-language flags (asian, use_space_remover, …)
text_normalizer.py      normalize_ocr_text() — CJK/full-width punct → ASCII, whitespace collapse
hotkey_listener.py      HotkeyListener(QObject) — global pause/resume hotkey; NSEvent monitors on macOS, pynput on Windows/Linux

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
version.py              APP_VERSION + GITHUB_REPO constants (single source of truth)
update_checker.py       UpdateCheckerThread — checks GitHub releases + glossary index on startup
translate_apple.swift   macOS 26+ Translation framework Swift CLI (stdin→stdout JSON)
translate_apple         Compiled Swift binary (auto-built on first Apple engine use)
translate_windows.cs    Windows 11 24H2+ Translation framework C# CLI (stdin→stdout JSON)
translate_windows.exe   Compiled C# binary (auto-built via dotnet on first Windows engine use)
translate_windows.csproj  .NET project for translate_windows.cs

translator.spec         PyInstaller build spec (onedir + BUNDLE for macOS; onefile for Win/Linux)
.github/workflows/
  ci.yml                CI: run tests on every push and PR (macOS / Windows / Linux matrix)
  release.yml           CI: run tests then build + release on v* tags

tests/                  pytest test suite (pure modules only — no Qt, no display needed)
  test_lru_cache.py           LRUCache eviction, access-order, fuzzy get_or_similar
  test_glossary_service.py    CRUD, protect/restore roundtrip, fuzzy fallback, persistence
  test_translation_pipeline.py  Cache warmup, clear_cache, glossary integration
  test_block_merger.py        Merge conditions, threshold boundaries, bbox math
  test_config_manager.py      load/save defaults, key merging, malformed JSON fallback
  test_community_glossary.py  _parse_entries edge cases; fetch_index/fetch_glossary (mocked urllib)
  test_update_checker.py      _version_tuple parsing and comparison (pure function, no Qt)
  test_ocr_model.py           OCRBlock defaults and is_merged property
  test_language_descriptor.py LanguageDescriptor lookup by display name, flag values
  test_text_normalizer.py     CJK_PUNCT_MAP entries, normalize_ocr_text flag branches

doc/                    Developer documentation
  architecture.md         Data flow, module responsibilities, design decisions
  adding_engine.md        How to add a new translation engine
  adding_platform.md      Platform support matrix and porting guide
  glossary.md             How the glossary pipeline works
  distribution.md         Release process, PyInstaller spec, CI workflow, version bumping
```

## Key design rules

- **No Qt in pure modules.** `ocr_model`, `block_merger`, `color_sampler`,
  `translator_engine`, `glossary_service`, `translation_pipeline`, `community_glossary`,
  `language_descriptor`, `text_normalizer`, `capture/`, `ocr/` — none import PyQt6.
  Safe to test without a display. (`hotkey_listener` imports PyQt6 but has no widget deps.)

- **Non-blocking OCR loop with state tracking.** `OCRWorker.run()` never
  waits on an API call. Each tick classifies OCR blocks in priority order:
  (1) cache hit → emit immediately; (2) IoU > 0.8 + edit-distance < 2 match
  against `_tracked` → reuse existing translation without re-translating;
  (3) no match → enqueue for the single persistent consumer thread (drop-old
  strategy). Ghost rendering keeps blocks visible for `linger_frames` ticks
  after OCR misses, preventing flicker from brief detection failures.

- **Cache key = normalized OCR text.** `TranslationPipeline._normalize()` applies
  NFC unicode composition, CJK punctuation canonicalization (`text_normalizer`), whitespace
  collapse, and stray-character stripping so minor frame-to-frame OCR variations (different
  OCR engines encoding `，` vs `,`, fullwidth digits, etc.) all hash to the same entry.
  On an exact-key miss `get_cached()` falls back to a rapidfuzz fuzzy scan over the most
  recent 64 entries (threshold: 95% Asian, 90% non-Asian) — jittery OCR still hits the
  cache without a re-translation. Cached value = fully post-processed final result (glossary
  applied). Call `pipeline.clear_cache()` when glossary entries change.

- **Fuzzy glossary protect.** `GlossaryService.protect()` uses a two-pass strategy:
  Pass 1 tries exact regex matching (fast path). Pass 2 retries unmatched entries
  with a `rapidfuzz.distance.Levenshtein` sliding-window scan over the text. This
  tolerates OCR character confusion (e.g. Korean `무`↔`우`, `얼`↔`멀`) that would
  otherwise bypass glossary protection entirely. Absolute error budget: 1 char
  for terms ≤3 chars, 2 chars for longer terms. A placeholder contamination guard
  (`__` marker check) prevents Pass 1 substitutions from producing spurious
  fuzzy matches in Pass 2.

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
| `community_glossary_seen_version` | `0` | Last community glossary `index.json` version the user has seen; compared against remote on startup |
| `hotkey_pause` | `"<ctrl>+<alt>+p"` | Global pause/resume hotkey; pynput format (`<ctrl>+<alt>+p`); macOS uses NSEvent monitors, Windows/Linux use pynput; registered by `HotkeyListener` in `AppController`; no-op when selector is showing |
| `fuzzy_length_threshold` | `3` | Terms with space-stripped length ≤ this value use `fuzzy_short_max_distance`; longer terms use `fuzzy_long_max_distance` |
| `fuzzy_short_max_distance` | `1` | Max Levenshtein edit distance for short glossary terms during fuzzy protect Pass 2; set to `0` to disable for short terms |
| `fuzzy_long_max_distance` | `2` | Max Levenshtein edit distance for long glossary terms during fuzzy protect Pass 2; set to `0` to disable for long terms |

## Running tests

```bash
uv run python -m pytest tests/ -v
```

All 142 tests cover 10 pure modules and run in ~0.13 s with no display.
The `dummy` engine (returns originals) is used in pipeline tests — no API key or network needed.
Network calls in community_glossary tests are mocked with `unittest.mock.patch`.

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
- **Global hotkey not working** → macOS: uses Cocoa NSEvent monitors — requires Accessibility permission (System Settings → Privacy → Accessibility); check `config["hotkey_pause"]` syntax (`"<ctrl>+<alt>+p"`); console prints `[hotkey] ...` on error. Windows/Linux: pynput must be installed (`uv sync`)
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

## Update notifications

`AppController.__init__` starts `UpdateCheckerThread` (a `QThread`) immediately on launch.
The thread makes two network requests (6-second timeout each, stdlib `urllib`):

1. **App update** — `GET https://api.github.com/repos/dodooodo/msw-translation/releases/latest`
   Compares `tag_name` against `APP_VERSION` from `version.py`. If newer, emits `app_update_available(latest_str)`.

2. **Glossary update** — `GET` community `index.json`. Compares `version` field against
   `config["community_glossary_seen_version"]`. If newer, emits `glossary_update_available(remote_int)`.

If the check completes before `ControlWindow` exists (user still on the ROI selector),
results are stored as `_pending_app_update` / `_pending_glossary_version` on `AppController`
and delivered immediately when `launch_overlay()` creates `ControlWindow`.

`ControlWindow` renders an amber banner (`_update_banner`, hidden by default) above the
main control bar. Banner height (`_H_BANNER = 36`) is included in `_reposition()`:
- **Glossary update** — "✨ 社群詞彙表有更新" + `[立即更新]` opens `CommunityGlossaryDialog`
  and saves the new `community_glossary_seen_version` to `config.json` after import.
- **App update** — "🚀 新版本 vX.Y.Z 可下載" + `[前往下載]` opens browser to GitHub releases.
- `[✕]` dismisses without recording the version (banner reappears next launch).

To trigger an update notification for all users:
- **Glossary:** bump `"version"` in `msw-glossary/index.json` and push.
- **App:** push a new `v*` tag (CI builds the release; GitHub API returns the new tag).

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
