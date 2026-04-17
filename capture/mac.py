"""capture/mac.py — macOS screenshot via Quartz CGWindowListCreateImage."""

import Quartz
from capture.base import CaptureProvider


class MacCaptureProvider(CaptureProvider):
    def grab(self, roi: tuple[int, int, int, int],
             below_win_id: int | None = None):
        x, y, w, h = roi
        rect = Quartz.CGRectMake(x, y, w, h)

        if below_win_id:
            # Stealth capture: only pixels from windows below the overlay.
            # Prevents capturing the overlay's own translated text.
            cg_image = Quartz.CGWindowListCreateImage(
                rect,
                Quartz.kCGWindowListOptionOnScreenBelowWindow,
                below_win_id,
                Quartz.kCGWindowImageDefault,
            )
        else:
            cg_image = Quartz.CGWindowListCreateImage(
                rect,
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
                Quartz.kCGWindowImageDefault,
            )

        return cg_image  # CGImageRef or None
