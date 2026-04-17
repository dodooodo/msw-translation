# Platform Support

## Current status

| Feature | macOS | Windows 10/11 | Linux |
|---------|-------|---------------|-------|
| Screen capture | ✅ `capture/mac.py` | ✅ `capture/cross.py` | ✅ `capture/cross.py` |
| OCR | ✅ `ocr/mac.py` | ✅ `ocr/windows.py` | ✅ `ocr/tesseract.py` |
| Built-in translation | ✅ `translate_apple` (macOS 26+) | ✅ `translate_windows.exe` (Win 11 24H2+) | — |
| Google Translate | ✅ | ✅ | ✅ |
| Color sampling | ✅ | — | — |
| Overlay rendering | ✅ | ✅ | ✅ |

macOS and Windows are fully implemented. Linux uses Tesseract OCR + Google Translate.

---

## Factory dispatch

Both factories select the right provider based on `sys.platform`:

```python
# capture/__init__.py
def get_provider():
    if sys.platform == "darwin":
        from capture.mac import MacCaptureProvider
        return MacCaptureProvider()
    # Windows and Linux both use mss
    from capture.cross import MssCaptureProvider
    return MssCaptureProvider()

# ocr/__init__.py
def get_provider():
    if sys.platform == "darwin":
        from ocr.mac import VisionOCRProvider
        return VisionOCRProvider()
    if sys.platform == "win32":
        from ocr.windows import WindowsOCRProvider
        return WindowsOCRProvider()
    # Linux fallback
    from ocr.tesseract import TesseractOCRProvider
    return TesseractOCRProvider()
```

---

## Adding a new platform

To support a new OS (e.g. a future Linux distro with a native ML OCR engine):

### 1. Implement `CaptureProvider`

```python
# capture/myplatform.py
from capture.base import CaptureProvider

class MyPlatformCaptureProvider(CaptureProvider):
    def grab(self, roi: tuple[int, int, int, int],
             below_win_id: int | None = None):
        # Return any image object — it will be passed directly to the
        # matching OCRProvider.recognize(). Format is opaque to callers.
        ...
```

`below_win_id` (macOS only) — ignore on other platforms.

### 2. Implement `OCRProvider`

```python
# ocr/myplatform.py
from ocr.base import OCRProvider
from ocr_model import OCRBlock

class MyPlatformOCRProvider(OCRProvider):
    def recognize(self, image, roi_w, roi_h, languages, custom_words=None):
        # languages: list of BCP-47 codes from OCR_LANG_MAP, e.g. ["ko-KR"]
        # Return list[OCRBlock] with text, bbox=(x,y,w,h), conf∈[0,1]
        ...
```

### 3. Register in the factories

Add an `elif sys.platform == "myplatform"` branch in both `capture/__init__.py`
and `ocr/__init__.py` before the existing fallback.

### 4. Add translation engine (optional)

If the platform has a built-in translation API, follow the subprocess pattern:

1. Write a CLI helper (Swift/C#/any) that reads `{"texts":[…], "source":"ko", "target":"zh-Hant"}`
   from stdin and writes `["…translated…"]` to stdout.
2. Auto-compile on first use in `translator_engine.py` (see `_ensure_apple_binary` /
   `_ensure_windows_binary` for the pattern).
3. Add a `_translate_myplatform()` function and wire it in `engine_translate()`.
4. Add the engine key to `settings_ui.py` combo + rev_map.

### 5. Color sampling

`color_sampler.annotate_colors()` checks `sys.platform == "darwin"` and is a silent
no-op elsewhere. Blocks keep default colors (`#ffffff` / `#000000`). No action needed
unless you want per-platform pixel sampling.

---

## Notes on existing implementations

### Windows (`ocr/windows.py`)

Uses `Windows.Media.Ocr` via the `winrt` Python package. The async WinRT API is
driven synchronously with `asyncio.run()`. Converts `mss.ScreenShot` → PIL Image →
BMP bytes → `InMemoryRandomAccessStream` → `SoftwareBitmap` (Bgra8) → `OcrEngine`.

No confidence scores are available (`conf=1.0` for all blocks).
No custom word hints (Windows.Media.Ocr has no equivalent of Vision's `customWords`).

### Linux (`ocr/tesseract.py`)

Requires `tesseract-ocr` and language packs installed at the OS level:
```bash
sudo apt install tesseract-ocr tesseract-ocr-kor tesseract-ocr-jpn \
    tesseract-ocr-chi-tra tesseract-ocr-chi-sim
```

Passes glossary terms as `--user-words` via a temp file for OCR hinting.
