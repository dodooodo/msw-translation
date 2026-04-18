"""capture/cross.py — Cross-platform screenshot via mss (Windows / Linux)."""

from capture.base import CaptureProvider


class MssCaptureProvider(CaptureProvider):
    def grab(self, roi: tuple[int, int, int, int],
             below_win_id: int | None = None):
        """
        below_win_id is ignored on non-macOS platforms (no equivalent API).
        Returns an mss screenshot object with a .rgb / .raw attribute.
        """
        try:
            import mss
        except ImportError:
            raise RuntimeError(
                "mss is not installed. Run: pip install mss"
            )

        x, y, w, h = roi
        monitor = {"left": x, "top": y, "width": w, "height": h}
        with mss.mss() as sct:
            return sct.grab(monitor)  # mss.ScreenShot

    def fingerprint(self, image) -> int | None:
        """Hash raw BGRA bytes. Returns None if the image cannot be read."""
        if image is None:
            return None
        try:
            return hash(bytes(image.raw))
        except Exception:
            return None
