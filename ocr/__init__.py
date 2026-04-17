"""ocr/__init__.py — Platform OCR factory + shared language map."""

import sys
from ocr.base import OCRProvider

# Single definition of the language map — replaces the identical dicts
# that previously existed in OCRWorker and RawOCRWorker.
OCR_LANG_MAP: dict[str, list[str]] = {
    "Korean":             ["ko-KR"],
    "Japanese":           ["ja-JP"],
    "English":            ["en-US"],
    "Traditional Chinese":["zh-Hant"],
    "Simplified Chinese": ["zh-Hans"],
}


def get_provider() -> OCRProvider:
    if sys.platform == "darwin":
        from ocr.mac import VisionOCRProvider
        return VisionOCRProvider()
    if sys.platform == "win32":
        from ocr.windows import WindowsOCRProvider
        return WindowsOCRProvider()
    from ocr.tesseract import TesseractOCRProvider
    return TesseractOCRProvider()
