"""update_checker.py — Background check for app and glossary updates.

Runs once on startup in a QThread. Emits signals if newer versions exist.
Pure stdlib — no third-party deps.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

from version import APP_VERSION, GITHUB_REPO
from community_glossary import COMMUNITY_INDEX_URL

_TIMEOUT = 6  # seconds


def _version_tuple(tag: str) -> tuple[int, ...]:
    """'v0.2.1' or '0.2.1' → (0, 2, 1)"""
    return tuple(int(x) for x in tag.lstrip("v").split(".") if x.isdigit())


class UpdateCheckerThread(QThread):
    app_update_available      = pyqtSignal(str)  # latest version string e.g. "0.2.0"
    glossary_update_available = pyqtSignal(int)  # remote index version

    def __init__(self, seen_glossary_version: int):
        super().__init__()
        self._seen = seen_glossary_version

    def run(self) -> None:
        self._check_app()
        self._check_glossary()

    def _check_app(self) -> None:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "msw-translation-updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest_tag = data.get("tag_name", "")
            if not latest_tag:
                return
            if _version_tuple(latest_tag) > _version_tuple(APP_VERSION):
                self.app_update_available.emit(latest_tag.lstrip("v"))
        except (URLError, ValueError, KeyError):
            pass

    def _check_glossary(self) -> None:
        try:
            with urllib.request.urlopen(COMMUNITY_INDEX_URL, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            remote_version = int(data.get("version", 0))
            if remote_version > self._seen:
                self.glossary_update_available.emit(remote_version)
        except (URLError, ValueError):
            pass
