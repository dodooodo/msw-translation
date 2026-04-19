# Architecture

## Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Qt Main Thread                       │
│                                                          │
│  SnippingToolWindow  ──roi──►  AppController             │
│                                    │                     │
│                         ┌──────────┼──────────┐          │
│                         ▼          ▼           ▼         │
│              TranslatorOverlay  ControlWindow  ...        │
│                    ▲                                      │
│           result_ready signal                            │
└───────────────────────────────────────────────────────── ┘
                         ▲
                         │  QThread (OCRWorker)
┌────────────────────────┴────────────────────────────────┐
│  capture.grab()  →  ocr.recognize()  →  annotate_colors │
│       │                                                  │
│       └──► merge_blocks_by_proximity()                   │
│                    │                                     │
│       ┌────────────┴───────────────┐                     │
│       │ pipeline.get_cached()      │                     │
│       │  hit → emit #1 immediately │                     │
│       │  miss → enqueue job ───────┼──► _translation_    │
│       │   (replaces stale pending) │    consumer thread  │
│       │                            │     (single, persistent)
│       │                            │          │           │
│       │                            │    emit #2 when done │
│       └────────────────────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

## Module responsibilities

### Data model (`ocr_model.py`)

`OCRBlock` is the only data type that flows through the entire pipeline.
No module invents its own dict schema — everything is an `OCRBlock` attribute.

```
text        Raw OCR string (source language)
bbox        (x, y, w, h) logical pixels within the ROI
conf        OCR confidence [0.0, 1.0]
text_color  Sampled from screenshot (#hex) — filled by color_sampler
bg_color    Sampled from screenshot (#hex) — filled by color_sampler
translated  Final display string — filled by TranslationPipeline
sub_bboxes  Original per-line bboxes when block_merger joined multiple rows
sub_texts   Original per-line OCR strings
sub_colors  Per-line (text_color, bg_color) pairs
```

`is_merged` is a property (`len(sub_bboxes) > 1`), not a stored field.

### Capture layer (`capture/`)

Responsibility: return a platform image object for a given ROI.
The image format is opaque to callers other than the matching OCR provider.

| Provider | Image type | Platform |
|----------|-----------|----------|
| `MacCaptureProvider` | `CGImageRef` | macOS |
| `MssCaptureProvider` | `mss.ScreenShot` | Windows / Linux |

`grab(roi, below_win_id, game_win_id)` has three capture modes (priority order):

1. **`game_win_id` set** — `CGWindowListCreateImageFromArray([game_win_id], rect, ...)`:
   reads directly from the window server backing store of the specified window.
   Works even when the game is fully covered by other windows.
2. **`below_win_id` set** — `kCGWindowListOptionOnScreenBelowWindow`: captures all
   pixels below the overlay, preventing the translated text from being re-OCR'd.
3. **Neither** — `kCGWindowListOptionOnScreenOnly`: plain screen capture.

`window_finder.py` provides two helpers called at overlay startup:

- `find_window_client_rect(title)` — returns `(x, y, w, h)` of the client area
  (title bar excluded). macOS: two-pass — osascript Accessibility API first, then
  Quartz `CGWindowListOptionAll` fallback (needed for Metal/OpenGL games). Windows:
  `FindWindowW` + `GetClientRect` + `ClientToScreen` via ctypes. Linux: xdotool subprocess.
- `find_game_window_id(title)` — returns the macOS CGWindowID for use with `grab()`.

### OCR providers

| Provider | Input | Platform |
|----------|-------|----------|
| `VisionOCRProvider` | `CGImageRef` | macOS (Apple Vision) |
| `WindowsOCRProvider` | `mss.ScreenShot` | Windows 10/11 (Windows.Media.Ocr via `winrt`) |
| `TesseractOCRProvider` | `mss.ScreenShot` | Linux (pytesseract fallback) |

`WindowsOCRProvider.recognize()` runs an `asyncio.run()` internally to drive the WinRT
async OCR API synchronously from the worker thread. The mss screenshot is converted to
a `SoftwareBitmap` (Bgra8) via PIL + `InMemoryRandomAccessStream` + `BitmapDecoder`.

`game_win_id` (macOS only): when set, `CGWindowListCreateImageFromArray` targets
the game window's backing store directly — works even when the game is occluded.
`below_win_id` (macOS only): fallback mode; captures only windows beneath the overlay
so the translated text is never re-OCR'd.

### OCR layer (`ocr/`)

Responsibility: convert a platform image into a list of `OCRBlock`.
Fills `text`, `bbox`, `conf`. Does not fill `text_color` / `bg_color`.

`OCR_LANG_MAP` lives here as the single authoritative mapping from config
language names (`"Korean"`) to engine-specific codes (`["ko-KR"]`).

### Color sampler (`color_sampler.py`)

Responsibility: fill `text_color` and `bg_color` on each block by sampling
raw pixels from the CGImage. macOS-only; `annotate_colors()` is a silent
no-op on other platforms.

**Algorithm:**
1. Sub-sample bbox interior with step = max(3, min(w,h)//8)
2. Background = 5-bit quantized mode of samples → averaged with neighbors ±20
3. Text color = pixels with distance > 40 from background, top-third by distance, averaged

Uses `CGDataProviderCopyData` + raw byte indexing (~1000× faster than `NSBitmapImageRep.colorAtX_y_()`).

**Retina scale:** CGImage is physical pixels (2× on Retina); bbox coords are
logical. Scale factor `sx = img_w / logical_w` converts before sampling.

**BGRA detection:** `CGImageGetBitmapInfo & 0x2000` detects Apple Silicon byte order.

### Block merger (`block_merger.py`)

Merges vertically adjacent OCR lines into single-sentence blocks.
Three conditions must all hold:

1. **Font size similar** — row-height ratio < 1.2
2. **Vertical gap small** — gap < average row height × 0.8
3. **Horizontal overlap** — ≥ 30% of the narrower block's width
   (prevents left/right separate UI panels from being joined)

Merged blocks carry `sub_bboxes / sub_texts / sub_colors` so the renderer
can position each translated line at its original row's pixel location.

### Language descriptor (`language_descriptor.py`)

`LanguageDescriptor` is a frozen dataclass that bundles all per-language flags in one
place, replacing scattered `if lang == "Korean"` branches across the codebase.

| Field | Purpose |
|-------|---------|
| `code` | BCP-47 tag (`"ko-KR"`) |
| `display_name` | Matches `config["source_language"]` values |
| `asian` | Selects fuzzy-cache threshold (95% vs 90%) |
| `use_end_punctuation` | Append trailing period for European languages |
| `use_space_remover` | Collapse spaces for CJK cache keys (Japanese/Chinese) |
| `use_word_tokenizer` | Reserved |
| `ocr_languages` | Hints passed to the OCR provider |

`get(display_name)` is the sole lookup function; falls back to Korean if unknown.
`ocr/__init__.py` derives `OCR_LANG_MAP` directly from `LANGUAGES` so the two are
never out of sync.

### OCR text normalizer (`text_normalizer.py`)

`normalize_ocr_text(text, *, is_asian, use_end_punctuation, use_space_remover) -> str`
canonicalizes OCR output for use as a cache key. Different OCR engines encode the same
glyph differently (Apple Vision → `，` U+FF0C; Windows OCR → `,` U+002C), creating
duplicate cache entries. The normalizer collapses 36 CJK punctuation/fullwidth-digit
variants to ASCII equivalents, trims stray edge characters, and optionally applies
language-specific rules from `LanguageDescriptor`.

Applied to **keys only** — raw text is still sent to the translation engine unmodified.

### Translation engine (`translator_engine.py`)

Responsibility: raw API calls only. No cache, no glossary, no pipeline logic.

`LRUCache` is thread-safe: all `get()`, `put()`, `clear()`, `__len__()` operations
are guarded by a `threading.Lock` to prevent `OrderedDict` corruption under
concurrent access from the OCR worker loop and translation consumer thread.

`get_or_similar(key, threshold=95.0, scan_limit=64) -> str | None` — fuzzy fallback
for jittery OCR output. Tries an exact lookup first; on miss, scans the `scan_limit`
most-recently-used entries with `rapidfuzz.fuzz.ratio` and returns the best result
above `threshold`, or `None`. Called by `TranslationPipeline.get_cached()` when the
normalized exact lookup misses.

| Engine | Implementation | Platform |
|--------|---------------|---------|
| `dummy` | Return originals | All |
| `apple` | `translate_apple` Swift subprocess | macOS 26+ |
| `windows` | `translate_windows.exe` C# subprocess | Windows 11 24H2+ |
| `google` | `googletrans` library | All |

`engine_translate(texts, config) -> list[str]` is the sole public function.

Both subprocess helpers (`translate_apple`, `translate_windows.exe`) are located via
`_bundle_dir()`, which returns `sys._MEIPASS` when running inside a PyInstaller bundle
and the project root otherwise. This makes the same code work for both `uv run` and
packaged `.app` / `.exe` without any path changes at call sites.

### Glossary service (`glossary_service.py`)

Manages user-defined term overrides. Data model treats entries as an i18n term dict
mapping multiple languages simultaneously.

**Two pipeline roles:**

- `protect(text, src, tgt, *, fuzzy_length_threshold, fuzzy_short_max_distance, fuzzy_long_max_distance)`
  — two-pass replacement of source terms with `[[T0]]`, `[[T1]]` … before translation:

  - **Pass 1 (exact)** — `re.compile(re.escape(term))` match; fast, zero overhead for hits.
  - **Pass 2 (fuzzy)** — sliding window + `rapidfuzz.distance.Levenshtein` for entries
    that didn't match exactly. Error budget: `fuzzy_short_max_distance` for terms ≤
    `fuzzy_length_threshold` chars (default 1 error), `fuzzy_long_max_distance` for longer
    terms (default 2 errors). Skips windows containing `[[` (placeholder contamination guard).

  Returns `(protected_text, {placeholder: target_term})`.

- `restore(text, placeholder_map)` — replaces placeholders with target terms after translation.

- `correct(text, src, tgt)` — fallback pass for any placeholders the engine garbled or lost.

Storage: `glossary.json` (JSON, human-readable, hand-editable).

### Version and update checker (`version.py`, `update_checker.py`)

`version.py` is the single source of truth for the app version and GitHub repo slug.
All version comparisons and release URLs derive from constants defined here.

`UpdateCheckerThread(QThread)` runs once on app startup. It makes two sequential
network requests (6 s timeout each, stdlib `urllib.request`):

1. `GET https://api.github.com/repos/{GITHUB_REPO}/releases/latest` — parses `tag_name`,
   compares tuple `(major, minor, patch)` against `APP_VERSION`, emits
   `app_update_available(str)` if newer.
2. `GET {COMMUNITY_INDEX_URL}` — reads top-level `"version"` integer, compares against
   `config["community_glossary_seen_version"]`, emits `glossary_update_available(int)` if newer.

Signals are connected to `ControlWindow.show_app_update()` / `show_glossary_update()`.
If the thread completes before `ControlWindow` is created, `AppController` buffers results
in `_pending_*` fields and delivers them in `launch_overlay()`.

### Community glossary (`community_glossary.py`)

Pure stdlib module (no third-party deps) for fetching community-shared glossaries
from the [dodooodo/msw-glossary](https://github.com/dodooodo/msw-glossary) GitHub repo.

```
fetch_index()  →  list[GlossaryMeta]
    Downloads index.json from COMMUNITY_INDEX_URL
    Each GlossaryMeta: name, game, languages (all 5), entry_count, raw_url

fetch_glossary(raw_url)  →  list[GlossaryEntry]
    Downloads a glossary file and deserializes entries
    Accepts any raw URL — GitHub, Gist, etc.
```

Always called from a `QThread` (`_FetchIndexWorker` / `_FetchGlossaryWorker` in
`settings_ui.py`) — never from the Qt main thread. 8-second timeout on all requests.

### Translation pipeline (`translation_pipeline.py`)

Orchestrates the full lifecycle: pre-process → engine → post-process + cache.
Injected into `OCRWorker` and any future user-input widget from `AppController`.

**Cache strategy (performance-critical):**
- Key = `_normalize(raw_text)` — NFC composition → CJK punct canonicalization
  (`text_normalizer`) → whitespace collapse → language-specific rules
  (trailing period, space removal) from `LanguageDescriptor`
- Value = fully post-processed final result
- **Exact hit:** `O(1)` dict lookup, zero glossary overhead
- **Fuzzy hit:** rapidfuzz scan over last 64 MRU entries (threshold 95%/90% Asian/non-Asian);
  if match found, result is written back under the exact key so next frame is O(1)
- **Miss:** full pipeline runs once; result stored; never repeated for that text
- Call `clear_cache()` after glossary changes

`translate_missing(texts)` — warms cache; intended for background threads.
`translate(texts) -> list[str]` — synchronous; for user-typed input or tests.

### OCRWorker (`translator.py`)

Thin QThread that orchestrates the pure modules.

**State tracking (`_tracked: list[_TrackedBlock]`):**
Each `_TrackedBlock` stores the last confirmed `OCRBlock`, its translation, and a
TTL countdown. A `confirmed` flag distinguishes blocks seen on the latest OCR pass
from ghost-only survivors so identical no-text frames can continue aging ghosts out
without deleting stable, still-visible text. Shared between the main loop and the
consumer thread under `_tracked_lock`.

**Per-tick classification (priority order):**
1. `capture.grab()` + `ocr.recognize(custom_words=…)` + `annotate_colors()` + `merge_blocks()`
2. For each block: `pipeline.get_cached(text)` — O(1) cache hit → emit immediately
3. **Mechanism 3 — Spatio-temporal match:** `tracking_utils.is_same_track()` (IoU > 0.8
   AND edit-distance ≤ 1) against `_tracked` → reuse existing translation, skip re-translation
4. No match → enqueue for consumer thread (drop-old strategy)

**Mechanism 4 — occlusion-aware ghost rendering:**
After matching, `_tracked` is rebuilt: fresh hits get full `linger_frames` TTL; any older
tracked block that is significantly covered by a newer OCR bbox is dropped immediately via
`tracking_utils.should_drop_tracked_block()` (`tracked_occlusion_threshold`, default 0.5).
Only unmatched, non-occluded tracked blocks are decremented and kept until TTL reaches 0.
Render = all entries still alive in `_tracked`, including ghosts. This prevents flicker
from brief OCR misses without letting overlapping stale boxes linger.

**Frame-diff skip aging:**
If `capture.fingerprint()` reports the same pixels as the previous processed frame, OCR is
skipped entirely. Confirmed blocks are kept as-is, but ghost-only blocks still have TTL
decremented so a static no-text frame can clear stale overlay content within `linger_frames`
ticks instead of leaving it visible indefinitely.

**Drop-old strategy:**
If a new OCR tick arrives while the consumer is still translating, the pending job slot is
**replaced** with the latest unmatched blocks — at most one `translate_apple` subprocess
runs at a time. The Qt event loop (and overlay repaint) is never blocked.

**`customWords`:**
Glossary source-language terms are passed to `ocr.recognize()` each tick as custom word
hints, biasing the OCR engine toward known game vocabulary and reducing variance.

### Qt UI (`translator.py`)

| Class | Role |
|-------|------|
| `SnippingToolWindow` | Full-screen ROI selector; drag to draw, click confirm; opens `SettingsDialog` |
| `TranslatorOverlay` | QPainter-based rendering; no QLabel (avoids macOS widget shadows); normal mode = pass-through; edit mode = clickable with bbox outlines |
| `EditPopup` | Floats over `TranslatorOverlay` in edit mode; pre-fills with OCR source + current translation; saves to glossary on confirm |
| `ControlWindow` | Dark glass bar: pause, text input, translate, ⊕ edit-mode toggle, stop; result pills; autocomplete popup; amber update banner (hidden until update detected) |
| `AppController` | Creates shared `config`, `GlossaryService`, `TranslationPipeline`; starts `UpdateCheckerThread`; starts `HotkeyListener` (global pause key); wires `mode_changed` → `overlay.set_edit_mode()`; buffers pending update signals until `ControlWindow` exists |

**Rendering notes:**
- `fillRect(bbox_width)` for background — never extends beyond the bbox
- `drawText` with `TextSingleLine` — prevents QPainter word-wrap
- `NSWindow.setHasShadow_(False)` via PyObjC in `showEvent` — eliminates macOS compositor shadow
- Font size = `max(10, int(bbox_height * 0.85))`
- `_sync_level_with_game(ns_window, game_win_id)` — called in `showEvent`; queries the
  game window's `kCGWindowLayer` via Quartz and sets `ns_window.setLevel_(game_level + 1)`.
  The overlay is one level above the game (never behind it) but below floating panels (3),
  modal dialogs (8), and system UI — so other apps that cover the game also cover the overlay.

**Edit mode:**
- `ControlWindow` emits `mode_changed("edit")` when the ⊕ button is pressed.
- `AppController` calls `overlay.set_edit_mode(True)`, which strips `WindowTransparentForInput`
  from the overlay's window flags and calls `show()` to recreate the native window handle.
- In edit mode `paintEvent` additionally draws `_BBOX_COLORS` outlines around each display item.
- `mousePressEvent` hit-tests click coordinates against `display_items` bboxes and calls
  `_show_edit_popup(item, pos)`.
- `EditPopup` pre-fills `_src_label` with `item["src"]` (raw OCR text) and `QLineEdit` with
  `item["trans"]` (current translation). On save it emits `saved(src_text, tgt_text)`.
- `TranslatorOverlay._on_glossary_save` creates a `GlossaryEntry` and calls
  `pipeline.glossary.add_entry(entry)` + `pipeline.clear_cache()`.
- Exiting edit mode restores `WindowTransparentForInput` so the overlay becomes pass-through again.

## Data flow (detailed)

```
capture.grab(roi, below_win_id, game_win_id)
    → CGImageRef / mss.ScreenShot
    (macOS: game_win_id → CGWindowListCreateImageFromArray; ignores occlusion)

ocr.recognize(image, roi_w, roi_h, languages, custom_words)
    → list[OCRBlock]  (text, bbox, conf; colors at defaults)

color_sampler.annotate_colors(image, blocks, logical_w, logical_h)
    → mutates block.text_color, block.bg_color  (macOS only)

block_merger.merge_blocks_by_proximity(blocks)
    → list[OCRBlock]  (sub_bboxes populated for merged groups)

for each block:
    pipeline.get_cached(block.text)
        exact hit  → O(1) cache lookup → fresh_translated.append(block)
        fuzzy hit  → rapidfuzz scan (last 64 MRU, threshold 95%/90%)
                     → warms exact key → fresh_translated.append(block)
        miss → spatio-temporal match in _tracked (IoU > 0.8 + edit-dist ≤ 1)
                   match → reuse tracked.translation (no re-translate)
                   no match → new_blocks / missing

_tracked rebuilt:
    fresh hits → full TTL, confirmed=True
    occluded stale tracks → drop immediately
    unmatched survivors → TTL-1, confirmed=False, keep if TTL>0
emit result_ready(render_now)          ← fresh + state matches + ghosts

if capture fingerprint unchanged:
    skip OCR entirely
    decrement TTL only for confirmed=False ghost entries
    emit result_ready(render_now) if any ghosts changed/expired

[single consumer thread]  ← replaces stale pending job (drop-old)
    pipeline.translate_missing(missing_texts)
        Pass 1: glossary.protect(text) — exact regex
        Pass 2: glossary.protect(text) — fuzzy Levenshtein fallback
        engine_translate(protected_texts)
        glossary.restore(result)
        glossary.correct(result)
        cache.put(normalized_text, final_result)
    appends new _TrackedBlock entries to _tracked (under lock)
    but skips any late result now occluded by newer OCR content

emit result_ready(render_complete)     ← new translations + all ghosts

TranslatorOverlay._flatten(blocks)
    → list[{bbox, trans, text_color, bg_color, src}]
    (splits translated text across sub_bboxes proportionally by char count;
     "src" = raw OCR text for the sub-line, used by EditPopup)

paintEvent draws each item in display_items (OCR blocks):
    fillRect  → bg_color
    drawText  → text_color, TextSingleLine
```

### User-input path (ControlWindow)

Both paths display the result in `_result_row`: clickable `[input] → [translated]` pills.
Clicking either pill copies it to the clipboard. Translation direction is reversed from OCR
(user types target language, e.g. Chinese; receives source language, e.g. Korean).

**Engine translation** (typed text + Enter / "翻譯"):

```
QLineEdit
    │  user types text (target language) and presses Enter or "翻譯"
    ▼
_on_submit()
    │  glossary protect: known target terms → [[Tn]] placeholders
    │  engine_translate([protected], reversed config)  ← synchronous; blocks briefly
    │  glossary restore: placeholders → source terms
    ▼
_btn_tgt.setText(input_text)
_btn_src.setText(translated_result)
_result_row.show()
```

**Glossary lookup** (autocomplete popup):

```
QLineEdit.textChanged → _update_suggestions()   ← prefix-match glossary entries
    │  user clicks a suggestion in the popup
    ▼
_on_suggestion_clicked()
    │  no translation — direct from glossary entry
    ▼
_btn_tgt.setText(entry.target_term)
_btn_src.setText(entry.source_term)
_result_row.show()
```

## Testing

Pure modules have no Qt or platform dependencies and can be tested without a display:

```bash
uv run python -m pytest tests/ -v   # 159 tests, ~0.12 s
```

| Test file | Module under test | Key scenarios |
|-----------|-------------------|---------------|
| `tests/test_lru_cache.py` | `LRUCache` | eviction order, access refresh, clear, fuzzy get_or_similar |
| `tests/test_glossary_service.py` | `GlossaryService` | CRUD, protect/restore roundtrip, fuzzy fallback (1 and 2 OCR errors), placeholder contamination, persistence |
| `tests/test_translation_pipeline.py` | `TranslationPipeline` | cache warmup, clear_cache, glossary integration |
| `tests/test_block_merger.py` | `merge_blocks_by_proximity` | merge conditions, threshold boundaries, bbox math |
| `tests/test_tracking_utils.py` | `tracking_utils` | bbox overlap, same-track detection, occlusion replacement decisions |
| `tests/test_config_manager.py` | `load_config` / `save_config` | defaults, key merging, malformed JSON fallback |
| `tests/test_community_glossary.py` | `community_glossary` | parse_entries edge cases; fetch_index/fetch_glossary (mocked urllib) |
| `tests/test_update_checker.py` | `_version_tuple` | parsing, comparison (pure function, no Qt) |
| `tests/test_ocr_model.py` | `OCRBlock` | defaults, is_merged property |
| `tests/test_language_descriptor.py` | `language_descriptor` | lookup by display name, flag values per language |
| `tests/test_text_normalizer.py` | `text_normalizer` | all 36 CJK_PUNCT_MAP entries, normalize_ocr_text flag branches |

Pipeline tests use `translator_engine: "dummy"` — no API key or network needed.

## Coordinate systems

| Space | Origin | Y direction | Used in |
|-------|--------|------------|---------|
| Screen logical | Top-left of screen | Down | Qt geometry, ROI |
| Vision normalized | Bottom-left of image | Up | VNRecognizeTextRequest output |
| CGImage physical | Top-left of image | Down | Quartz pixel sampling |

**Vision → logical:** `px = nx * roi_w`, `py = (1 - ny - nh) * roi_h`

**Logical → physical (Retina):** `scale = img_w / roi_w`; multiply before pixel access
