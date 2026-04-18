"""hotkey_listener.py

Cross-platform global keyboard hotkey with a Qt-signal interface.

Users in fullscreen/borderless games can't reach ControlWindow without
alt-tabbing, which many games don't recover from gracefully.  A global
hotkey (default ``Ctrl+Alt+P``) lets them pause OCR without leaving the game.

The pynput callback fires on a background thread; emitting a Qt signal from
there is safe because Qt auto-promotes cross-thread signal delivery to a
queued connection, which re-enters the GUI thread's event loop.

macOS crash note: pynput's CGEventTap callback (_handler) is decorated with
@_emitter, which re-raises any exception after storing it.  That re-raise
escapes into the CoreGraphics C callback frame and causes a native abort().
_SafeGlobalHotKeys wraps _handler in try/except BaseException so nothing
ever escapes the Python boundary — caps-lock and other modifier events that
pynput cannot map are silently discarded.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyListener(QObject):
    """Wraps ``pynput.keyboard.GlobalHotKeys``; emits ``triggered`` on press."""

    triggered = pyqtSignal()

    def __init__(self, hotkey: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._listener = None  # _SafeGlobalHotKeys — lazy-imported

    def start(self) -> bool:
        """Start listening.  Returns True on success, False if pynput or the
        OS accessibility permission is unavailable."""
        if self._listener is not None:
            return True
        try:
            from pynput import keyboard
        except Exception as e:
            print(f"[hotkey] pynput import failed: {e}")
            return False

        # Subclass to swallow the re-raise that @_emitter performs after storing
        # an exception.  Without this, a Caps Lock keypress (or any event that
        # pynput cannot decode) raises inside the CGEventTap C callback and
        # causes a native abort() that terminates the whole app.
        class _SafeGlobalHotKeys(keyboard.GlobalHotKeys):
            def _handler(self, proxy, event_type, event, refcon):
                try:
                    return super()._handler(proxy, event_type, event, refcon)
                except BaseException:
                    pass

        try:
            self._listener = _SafeGlobalHotKeys({self._hotkey: self._on_press})
            self._listener.start()
            return True
        except Exception as e:
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
