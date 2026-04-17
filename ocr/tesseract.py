"""ocr/tesseract.py — pytesseract OCR provider (Windows / Linux fallback)."""

from ocr_model import OCRBlock
from ocr.base  import OCRProvider


class TesseractOCRProvider(OCRProvider):
    def recognize(
        self,
        image,   # mss.ScreenShot from MssCaptureProvider
        roi_w: float,
        roi_h: float,
        languages: list[str],
        custom_words: list[str] | None = None,
    ) -> list[OCRBlock]:
        try:
            import pytesseract
            from PIL import Image
            import numpy as np
        except ImportError:
            raise RuntimeError(
                "pytesseract and Pillow are required on non-macOS platforms. "
                "Run: pip install pytesseract pillow"
            )

        # Convert mss screenshot to PIL Image
        img = Image.frombytes("RGB", image.size, image.rgb)

        # Map BCP-47 codes to tesseract lang strings
        lang_map = {
            "ko-KR": "kor",
            "ja-JP": "jpn",
            "en-US": "eng",
            "zh-Hant": "chi_tra",
            "zh-Hans": "chi_sim",
        }
        tess_langs = "+".join(lang_map.get(l, "eng") for l in languages) or "eng"

        # Pass glossary terms as custom word hints via a temp file
        import os, tempfile
        words_file = None
        config = ""
        if custom_words:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write("\n".join(custom_words))
                words_file = f.name
            config = f"--user-words {words_file}"

        try:
            data = pytesseract.image_to_data(
                img, lang=tess_langs, config=config,
                output_type=pytesseract.Output.DICT,
            )
        finally:
            if words_file:
                os.unlink(words_file)

        blocks: list[OCRBlock] = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            if not text or conf < 0:
                continue
            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]
            blocks.append(OCRBlock(
                text = text,
                bbox = (float(x), float(y), float(w), float(h)),
                conf = conf / 100.0,
            ))

        return blocks
