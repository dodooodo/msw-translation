"""capture/mac.py — macOS screenshot via Quartz CGWindowListCreateImage."""

import Quartz
from capture.base import CaptureProvider


class MacCaptureProvider(CaptureProvider):
    def grab(self, roi: tuple[int, int, int, int],
             below_win_id: int | None = None,
             game_win_id: int | None = None):
        x, y, w, h = roi
        rect = Quartz.CGRectMake(x, y, w, h)

        if game_win_id:
            # Game-window capture: read directly from the window server's
            # backing store for this specific window, so other windows
            # covering the game do not interfere.
            cg_image = Quartz.CGWindowListCreateImageFromArray(
                rect,
                [game_win_id],
                Quartz.kCGWindowImageDefault,
            )
        elif below_win_id:
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

    def fingerprint(self, image) -> int | None:
        """Hash raw pixel bytes. Returns None if the image cannot be read."""
        if image is None:
            return None
        try:
            dp = Quartz.CGImageGetDataProvider(image)
            cf_data = Quartz.CGDataProviderCopyData(dp)
            return hash(bytes(cf_data))
        except Exception:
            return None
