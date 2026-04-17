"""ocr/windows.py — Windows.Media.Ocr provider via winrt (Windows 10/11)."""

import asyncio
from io import BytesIO

from ocr_model import OCRBlock
from ocr.base import OCRProvider


class WindowsOCRProvider(OCRProvider):
    def recognize(
        self,
        image,   # mss.ScreenShot from MssCaptureProvider
        roi_w: float,
        roi_h: float,
        languages: list[str],
        custom_words: list[str] | None = None,
    ) -> list[OCRBlock]:
        try:
            return asyncio.run(self._recognize_async(image, languages))
        except Exception as e:
            print(f"[Windows OCR] 錯誤: {e}")
            return []

    async def _recognize_async(self, image, languages: list[str]) -> list[OCRBlock]:
        import winrt.windows.media.ocr as ocr_winrt
        import winrt.windows.globalization as globalization
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.storage.streams as streams
        from PIL import Image

        # mss screenshot → PIL Image → BMP bytes
        img = Image.frombytes("RGB", image.size, image.rgb).convert("RGBA")
        buf = BytesIO()
        img.save(buf, format="BMP")
        buf.seek(0)
        bmp_bytes = buf.read()

        # Load into WinRT in-memory stream
        ras = streams.InMemoryRandomAccessStream()
        writer = streams.DataWriter(ras.get_output_stream_at(0))
        writer.write_bytes(list(bmp_bytes))
        await writer.store_async()
        ras.seek(0)

        # Decode to SoftwareBitmap (Bgra8 required by OcrEngine)
        decoder = await imaging.BitmapDecoder.create_async(ras)
        soft_bmp = await decoder.get_software_bitmap_async()
        if soft_bmp.bitmap_pixel_format != imaging.BitmapPixelFormat.BGRA8:
            soft_bmp = imaging.SoftwareBitmap.convert(
                soft_bmp, imaging.BitmapPixelFormat.BGRA8
            )

        # Pick OCR engine — try each requested language code in order
        engine = None
        for lang_code in languages:
            try:
                lang = globalization.Language(lang_code)
                engine = ocr_winrt.OcrEngine.try_create_from_language(lang)
                if engine:
                    break
            except Exception:
                continue
        if engine is None:
            engine = ocr_winrt.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            print("[Windows OCR] 找不到可用的 OCR 語言引擎")
            return []

        result = await engine.recognize_async(soft_bmp)

        blocks: list[OCRBlock] = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            line_text = " ".join(w.text for w in words).strip()
            if not line_text:
                continue
            x = min(w.bounding_rect.x for w in words)
            y = min(w.bounding_rect.y for w in words)
            r = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
            b = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
            blocks.append(OCRBlock(
                text=line_text,
                bbox=(float(x), float(y), float(r - x), float(b - y)),
                conf=1.0,  # Windows.Media.Ocr does not expose per-word confidence
            ))

        return blocks
