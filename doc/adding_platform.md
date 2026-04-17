# Porting to a New Platform (Windows / Linux)

Two providers need concrete implementations: capture and OCR.
`translator.py` and all pure modules require zero changes.

## 1. Implement `CaptureProvider`

Create or fill in `capture/cross.py` (already stubbed):

```python
# capture/cross.py
from capture.base import CaptureProvider

class MssCaptureProvider(CaptureProvider):
    def grab(self, roi: tuple[int, int, int, int],
             below_win_id: int | None = None):
        import mss
        x, y, w, h = roi
        with mss.mss() as sct:
            return sct.grab({"left": x, "top": y, "width": w, "height": h})
        # Returns mss.ScreenShot — passed directly to OCRProvider.recognize()
```

`below_win_id` has no equivalent on Windows/Linux — ignore it. The overlay
window will be captured too, but since translated text is usually different
from the source language, it won't cause translation loops.

## 2. Implement `OCRProvider`

Fill in `ocr/tesseract.py` (already stubbed) or create a new file:

```python
# ocr/tesseract.py
from ocr.base  import OCRProvider
from ocr_model import OCRBlock

class TesseractOCRProvider(OCRProvider):
    def recognize(self, image, roi_w, roi_h, languages, custom_words=None):
        from PIL import Image
        import pytesseract

        img = Image.frombytes("RGB", image.size, image.rgb)
        lang_map = {"ko-KR": "kor", "ja-JP": "jpn", "en-US": "eng", ...}
        tess_lang = "+".join(lang_map.get(l, "eng") for l in languages)

        data = pytesseract.image_to_data(img, lang=tess_lang,
                                         output_type=pytesseract.Output.DICT)
        blocks = []
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            if not text or conf < 0:
                continue
            blocks.append(OCRBlock(
                text = text,
                bbox = (data["left"][i], data["top"][i],
                        data["width"][i], data["height"][i]),
                conf = conf / 100.0,
            ))
        return blocks
```

## 3. Register in the factories

```python
# capture/__init__.py
def get_provider():
    if sys.platform == "darwin":
        from capture.mac import MacCaptureProvider
        return MacCaptureProvider()
    else:
        from capture.cross import MssCaptureProvider
        return MssCaptureProvider()

# ocr/__init__.py
def get_provider():
    if sys.platform == "darwin":
        from ocr.mac import VisionOCRProvider
        return VisionOCRProvider()
    else:
        from ocr.tesseract import TesseractOCRProvider
        return TesseractOCRProvider()
```

Both factories already contain exactly this code — just ensure the
implementation files are complete.

## 4. Color sampling

`color_sampler.annotate_colors()` checks `sys.platform == "darwin"` and
returns immediately on other platforms. Blocks keep their default colors
(`#ffffff` / `#000000`). This is acceptable — color sampling is a
quality-of-life feature, not core functionality.

To add cross-platform color sampling, add an `else` branch in
`color_sampler.py` that converts the `mss.ScreenShot` to raw bytes and
applies the same mode-based algorithm.

## 5. macOS window shadow removal

`TranslatorOverlay.showEvent` calls `NSWindow.setHasShadow_(False)` via PyObjC.
On other platforms this try/except block fails silently — no action needed.

## Dependencies to add

```
mss              # cross-platform screenshot
pytesseract      # Python bindings for Tesseract OCR
pillow           # image conversion for pytesseract
```

Tesseract itself must be installed separately:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- Linux: `apt install tesseract-ocr tesseract-ocr-kor` (or relevant lang packs)
