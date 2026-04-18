"""hotkey_listener.py

Cross-platform global keyboard hotkey with a Qt-signal interface.

Users in fullscreen/borderless games can't reach ControlWindow without
alt-tabbing, which many games don't recover from gracefully.  A global
hotkey (default ``Ctrl+Alt+P``) lets them pause OCR without leaving the game.

The pynput callback fires on a background thread; emitting a Qt signal from
there is safe because Qt auto-promotes cross-thread signal delivery to a
queued connection, which re-enters the GUI thread's event loop.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyListener(QObject):
    """Wraps ``pynput.keyboard.GlobalHotKeys``; emits ``triggered`` on press."""

    triggered = pyqtSignal()

    def __init__(self, hotkey: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._listener = None  # pynput.keyboard.GlobalHotKeys — lazy-imported

    def start(self) -> bool:
        """Start listening.  Returns True on success, False if pynput or the
        OS accessibility permission is unavailable (we don't want a missing
        hotkey to crash the app)."""
        if self._listener is not None:
            return True
        try:
            from pynput import keyboard
        except Exception as e:
            print(f"[hotkey] pynput import failed: {e}")
            return False
        try:
            self._listener = keyboard.GlobalHotKeys({self._hotkey: self._on_press})
            self._listener.start()
            return True
        except Exception as e:
            # Invalid hotkey string or OS permission denied on macOS.
            print(f"[hotkey] failed to register '{self._hotkey}': {e}")
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _on_press(self) -> None:
        # Runs on pynput's background thread — safe because Qt signals cross
        # threads via an auto-queued connection into the main event loop.
        self.triggered.emit()
