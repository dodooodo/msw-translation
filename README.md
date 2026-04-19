# msw_translation

[![CI](https://github.com/dodooodo/msw-translation/actions/workflows/ci.yml/badge.svg)](https://github.com/dodooodo/msw-translation/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-blue)](https://github.com/dodooodo/msw-translation/releases)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

Real-time game overlay translator. Captures a region of your screen, recognises
text with OCR, and renders the translation as a transparent overlay on top —
without interrupting gameplay.

Built for MapleStory Worlds and similar games with Korean/Japanese/Chinese UI.

---

## Download

Grab the latest release for your platform from the
[**Releases page**](https://github.com/dodooodo/msw-translation/releases):

| Platform | File | Requirements |
|----------|------|--------------|
| macOS (Apple Silicon) | `MSW-Translator-*-macos-arm64.zip` | macOS 14+; macOS 26+ for Apple Translation |
| Windows | `MSW-Translator-*-windows-x64.zip` | Windows 10/11; Win 11 24H2+ for built-in translation |
| Linux | `MSW-Translator-*-linux-x64.tar.gz` | Tesseract: `sudo apt install tesseract-ocr` |

Unzip and run the app — no Python installation needed.

---

## Run from source

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/dodooodo/msw-translation.git
cd msw-translation

uv run translator.py
```

uv resolves and installs all dependencies automatically.

---

## Usage

1. Launch the app — if **MapleStory Worlds** is already running the game window
   is detected automatically and the overlay starts immediately (no manual selection needed)
2. If the game is not running, drag to select the game text area manually, then
   click **✅ 確認並開始翻譯** to start
3. Translated text appears as an overlay in real time, at the same window level
   as the game — other windows that cover the game will also cover the translations
4. Click **⏸ 暫停** (or press `Ctrl+Alt+P` globally) to freeze / clear the display
5. Click **⏹️ 退出並重新截圖** to re-select the area

---

## Platform support

| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Screen capture | ✅ Quartz | ✅ mss | ✅ mss |
| OCR | ✅ Apple Vision | ✅ Windows.Media.Ocr | ✅ Tesseract |
| Color sampling | ✅ | — | — |
| Apple Translation | ✅ macOS 26+ | — | — |
| Windows Translation | — | ✅ Win 11 24H2+ | — |
| Google Translation | ✅ | ✅ | ✅ |
| Overlay rendering | ✅ | ✅ | ✅ |

---

## Settings

Click **⚙️ 設定檔** in the selector toolbar.

| Setting | Description |
|---------|-------------|
| Source language | Language of the game UI (Korean, Japanese, English, …) |
| Target language | Language to translate into |
| Translation engine | Apple / Windows (built-in, best quality), Google, or Dummy |
| Font size | Base font size hint |
| Text color | Base text color hint |
| OCR interval | How often to scan the screen (seconds); 0.1 s = 10 fps |

---

## Glossary / Dictionary

The glossary pins specific term translations so the engine cannot mangle
game-specific proper nouns (item names, skill names, NPC names).

Open **⚙️ 設定檔 → 📖 詞彙表** to manage entries. You can paste multi-language
tables directly from Excel.

### Community glossaries

The **☁ Community Glossaries** button in the 詞彙表 tab lets you browse and
import game-specific glossaries shared by the community. The curated list is
maintained at [dodooodo/msw-glossary](https://github.com/dodooodo/msw-glossary).

To share your own glossary:
- **Quick share** — use **↓ Export** to save your `glossary.json`, then paste the
  raw URL (GitHub Gist, etc.) into **🔗 Import from URL** on another machine.
- **Contribute to the official list** — submit a PR to
  [msw-glossary](https://github.com/dodooodo/msw-glossary) or open an issue
  with your exported JSON.

### Manual format (`glossary.json`)

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

**How it works:**
1. Before translation — source terms are replaced with `[[T0]]` placeholders
2. **Fuzzy fallback** — any unmatched entries are retried with a sliding window substring search using Levenshtein distance. This tolerates OCR character confusion (e.g. `우`↔`무`).
3. After translation — placeholders are swapped back to target terms
4. Correction pass — any entries the engine garbled are fixed by string replacement

---

## Translation engines

### Apple (macOS 26+)
No API key required. macOS may download a language model on first use.

### Windows built-in (Windows 11 24H2+)
Uses the OS translation framework. No API key required. Falls back to Google
if the API is unavailable.

### Google
Uses the `googletrans` library (no API key for basic use).

```bash
uv add googletrans==4.0.0-rc1
```

### Dummy
Returns the original text unchanged — useful for testing OCR without network calls.

---

## Advanced config (`config.json`)

The following fields must be edited in `config.json` directly (not exposed in the UI).

### `min_confidence` (default: `0.0`)
Vision OCR confidence threshold (0–1). Blocks below this are dropped.
- `0.0` — accept everything (default)
- `0.3`–`0.5` — filter noisy detections

### `min_text_length` (default: `1`)
Minimum characters after stripping whitespace.
- `1` — only empty strings dropped (default)
- `2` — drops single isolated characters (use cautiously — Korean has meaningful single-char words)

### `merge_max_height_ratio` (default: `1.2`)
Max height ratio for two blocks to be considered the same font size and eligible to merge.

### `merge_gap_ratio` (default: `0.8`)
Vertical gap must be < `avg_height × ratio` for blocks to merge.

### `merge_min_h_overlap` (default: `0.3`)
Minimum horizontal overlap (fraction of the narrower block's width) to merge vertically adjacent blocks.

### `linger_frames` (default: `3`)
Ticks to keep an unmatched block as a short-lived ghost after an OCR miss
(~0.6 s at default interval). If a newer bbox clearly covers the old one,
the old bbox is dropped immediately instead of waiting for TTL to expire.

### `tracked_occlusion_threshold` (default: `0.5`)
How much of an old bbox must be covered by a newer bbox before the old tracked
block is treated as replaced and removed immediately.
- `0.5` — balanced default
- lower values — more aggressive cleanup of overlapping stale boxes
- higher values — more conservative; may keep overlapping ghosts longer

### `hotkey_pause` (default: `"<ctrl>+<alt>+p"`)
Global keyboard shortcut to pause/resume OCR from inside a fullscreen game — no
alt-tab required. Uses pynput format: modifier keys in angle brackets
(`<ctrl>`, `<alt>`, `<shift>`, `<cmd>`), regular keys bare (`p`, `f9`, etc.).
On macOS the hotkey is implemented via Cocoa NSEvent monitors; on Windows/Linux via pynput.

### `fuzzy_length_threshold` (default: `3`)
Char-count boundary (space-stripped) between "short" and "long" terms for the fuzzy matcher.

### `fuzzy_short_max_distance` (default: `1`)
Max absolute Levenshtein edit distance (OCR errors) allowed for short terms. Set to `0` to disable.

### `fuzzy_long_max_distance` (default: `2`)
Max absolute Levenshtein edit distance (OCR errors) allowed for long terms. Set to `0` to disable.

> **Why distance instead of a ratio?**
> A ratio threshold (e.g. 75%) rejects many medium-length terms (a 5-char term with 2 errors has only a 60% ratio). Absolute distance allows for a predictable error budget.

> **macOS note:** requires Accessibility permission (System Settings → Privacy & Security → Accessibility).
> macOS uses Cocoa NSEvent monitors (not pynput) so Caps Lock and other modifier keys cannot crash the app.
> This is the same permission already needed for Quartz screen capture.

---

## Debug tool

```bash
uv run bbox_visualizer.py
```

Shows raw OCR bounding boxes as coloured frames with labels — useful for
diagnosing merge errors and bbox alignment.

---

## Developer docs

- [doc/architecture.md](doc/architecture.md) — Full data flow and design decisions
- [doc/adding_engine.md](doc/adding_engine.md) — Add a new translation engine
- [doc/adding_platform.md](doc/adding_platform.md) — Port to a new OS
- [doc/glossary.md](doc/glossary.md) — Glossary pipeline internals

---

## Project structure

```
main.py                 Entry point (run this)
translator.py           Qt UI classes (SnippingToolWindow, TranslatorOverlay, …)
bbox_visualizer.py      OCR debug visualiser

ocr_model.py            Shared OCRBlock dataclass
block_merger.py         Line merging logic
color_sampler.py        Pixel color analysis (macOS)
translator_engine.py    Translation engine dispatch + LRU cache
glossary_service.py     Glossary term protection
translation_pipeline.py Full pre→translate→post pipeline
community_glossary.py   Community glossary fetch (GitHub)
language_descriptor.py  Per-language flags (asian, space-remover, …)
text_normalizer.py      CJK punctuation normalizer for cache keys
tracking_utils.py       Pure bbox tracking helpers for same-track / occlusion decisions
hotkey_listener.py      Global pause hotkey (NSEvent on macOS, pynput on Win/Linux → Qt signal)

capture/                Platform screenshot abstraction
  mac.py                  Quartz (macOS); game-window-specific capture via CGWindowListCreateImageFromArray
  cross.py                mss (Windows / Linux)
  window_finder.py        Auto-detect game window bounds and CGWindowID (macOS/Windows/Linux)
ocr/                    Platform OCR abstraction
  mac.py                  Apple Vision (macOS)
  windows.py              Windows.Media.Ocr (Windows)
  tesseract.py            Tesseract (Linux)

config_manager.py       Config file I/O
settings_ui.py          Settings dialog
translate_apple.swift   macOS Translation framework CLI helper
translate_windows.cs    Windows Translation framework CLI helper
```

---

## Contributing

Issues and PRs welcome. For glossary contributions, see
[dodooodo/msw-glossary](https://github.com/dodooodo/msw-glossary).

## License

[MIT](LICENSE) © 2026 dodooodo
