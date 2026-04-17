"""ocr/mac.py — Apple Vision VNRecognizeTextRequest OCR provider."""

from Vision import (
    VNImageRequestHandler,
    VNRecognizeTextRequest,
    VNRequestTextRecognitionLevelAccurate,
)
from ocr_model  import OCRBlock
from ocr.base   import OCRProvider


class VisionOCRProvider(OCRProvider):
    def recognize(
        self,
        image,   # CGImageRef from MacCaptureProvider
        roi_w: float,
        roi_h: float,
        languages: list[str],
        custom_words: list[str] | None = None,
    ) -> list[OCRBlock]:
        if image is None:
            return []

        handler = VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        blocks: list[OCRBlock] = []

        def on_done(request, error):
            if error:
                return
            for obs in (request.results() or []):
                candidates = obs.topCandidates_(1)
                if not candidates:
                    continue
                text = candidates[0].string().strip()
                if not text:
                    continue
                bb = obs.boundingBox()
                nx, ny, nw, nh = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
                blocks.append(OCRBlock(
                    text = text,
                    bbox = (nx * roi_w,
                            (1.0 - ny - nh) * roi_h,
                            nw * roi_w,
                            nh * roi_h),
                    conf = float(candidates[0].confidence()),
                ))

        req = VNRecognizeTextRequest.alloc().initWithCompletionHandler_(on_done)
        req.setRecognitionLevel_(VNRequestTextRecognitionLevelAccurate)

        # Disable language correction — prevents the engine from mangling
        # game-specific proper nouns into real-world dictionary words.
        if hasattr(req, "setUsesLanguageCorrection_"):
            req.setUsesLanguageCorrection_(False)
        if hasattr(req, "setRecognitionLanguages_") and languages:
            req.setRecognitionLanguages_(languages)
        if hasattr(req, "setCustomWords_") and custom_words:
            req.setCustomWords_(custom_words)

        handler.performRequests_error_([req], None)
        return blocks
