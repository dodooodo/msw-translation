"""ocr/__init__.py — Platform OCR factory + shared language map."""

import sys
from ocr.base import OCRProvider
from language_descriptor import LANGUAGES

# Thin wrapper over LANGUAGES so OCR worker code can keep using dict-lookup style.
# The list shape is preserved because OCRProvider.recognize() expects a list,
# even though each language currently exposes exactly one BCP-47 tag.
OCR_LANG_MAP: dict[str, list[str]] = {
    name: list(desc.ocr_languages) for name, desc in LANGUAGES.items()
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
