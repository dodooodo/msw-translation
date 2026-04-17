"""capture/__init__.py — Platform capture factory."""

import sys
from capture.base import CaptureProvider


def get_provider() -> CaptureProvider:
    if sys.platform == "darwin":
        from capture.mac import MacCaptureProvider
        return MacCaptureProvider()
    else:
        from capture.cross import MssCaptureProvider
        return MssCaptureProvider()
