"""ocr/base.py — Abstract OCR provider interface."""

from abc import ABC, abstractmethod
from ocr_model import OCRBlock


class OCRProvider(ABC):
    @abstractmethod
    def recognize(
        self,
        image,
        roi_w: float,
        roi_h: float,
        languages: list[str],
        custom_words: list[str] | None = None,
    ) -> list[OCRBlock]:
        """
        Run text recognition on `image` and return detected blocks.

        image     : platform-specific image from CaptureProvider.grab().
        roi_w/h   : logical dimensions of the captured region (used to convert
                    normalized Vision coords back to pixel coords).
        languages : list of BCP-47 language codes, e.g. ["ko-KR"].

        Returns OCRBlock list with text / bbox / conf filled.
        text_color and bg_color are left at defaults; color_sampler fills them.
        """
