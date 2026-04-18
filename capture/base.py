"""capture/base.py — Abstract capture provider interface."""

from abc import ABC, abstractmethod
from typing import Any


class CaptureProvider(ABC):
    @abstractmethod
    def grab(self, roi: tuple[int, int, int, int],
             below_win_id: int | None = None) -> Any:
        """
        Capture a screenshot of the given ROI.

        roi            : (x, y, width, height) in logical screen pixels.
        below_win_id   : macOS window number; when provided, only pixels
                         from windows below this one are captured (stealth
                         screenshot that excludes the overlay itself).

        Returns a platform-specific image object suitable for the
        corresponding OCRProvider.
        """

    def fingerprint(self, image: Any) -> int | None:
        """
        Return a content hash of the captured image, or None if unavailable.
        Same pixels → same hash; used to skip OCR on unchanged frames.
        Default: None (no skip). Platform providers override.
        """
        return None
