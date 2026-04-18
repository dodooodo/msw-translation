"""hotkey_listener.py

Cross-platform global keyboard hotkey with a Qt-signal interface.

Users in fullscreen/borderless games can't reach ControlWindow without
alt-tabbing, which many games don't recover from gracefully.  A global
hotkey (default ``Ctrl+Alt+P``) lets them pause OCR without leaving the game.

macOS implementation uses Cocoa's ``NSEvent`` global/local monitors instead
of pynput.  pynput's CGEventTap path re-raises callback exceptions into
the CoreGraphics C frame, which aborts the process on any untypable key
event (Caps Lock, some modifier transitions).  NSEvent monitors are a
higher-level API that does not have this failure mode.

Windows/Linux still use pynput — those backends don't have the re-raise
issue.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyListener(QObject):
    """Emits ``triggered`` whenever the configured global hotkey is pressed."""

    triggered = pyqtSignal()

    def __init__(self, hotkey: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._impl = None  # _MacImpl or _PynputImpl

    def start(self) -> bool:
        if self._impl is not None:
            return True
        if sys.platform == "darwin":
            impl = _MacImpl(self._hotkey, self._on_fire)
        else:
            impl = _PynputImpl(self._hotkey, self._on_fire)
        if impl.start():
            self._impl = impl
            return True
        return False

    def stop(self) -> None:
        if self._impl is not None:
            self._impl.stop()
            self._impl = None

    def _on_fire(self) -> None:
        self.triggered.emit()


# --- macOS: NSEvent global + local monitors ---------------------------------


class _MacImpl:
    """NSEvent-based monitor — no CGEventTap, no pynput."""

    def __init__(self, hotkey: str, on_fire) -> None:
        self._hotkey = hotkey
        self._on_fire = on_fire
        self._global_monitor = None
        self._local_monitor = None

    def start(self) -> bool:
        try:
            from AppKit import (
                NSEvent,
                NSEventMaskKeyDown,
            )
        except Exception as e:
            print(f"[hotkey] AppKit import failed: {e}")
            return False

        try:
            expected_mods, expected_char = _parse_mac_hotkey(self._hotkey)
        except ValueError as e:
            print(f"[hotkey] bad hotkey '{self._hotkey}': {e}")
            return False

        from AppKit import NSEventModifierFlagDeviceIndependentFlagsMask

        def matches(event) -> bool:
            mods = (
                event.modifierFlags() & NSEventModifierFlagDeviceIndependentFlagsMask
            )
            if mods != expected_mods:
                return False
            chars = event.charactersIgnoringModifiers()
            if not chars:
                return False
            return chars.lower() == expected_char

        def global_handler(event):
            try:
                if matches(event):
                    self._on_fire()
            except BaseException as exc:
                print(f"[hotkey] global handler error: {exc}")

        def local_handler(event):
            try:
                if matches(event):
                    self._on_fire()
                    return None  # swallow — don't pass to focused view
            except BaseException as exc:
                print(f"[hotkey] local handler error: {exc}")
            return event

        try:
            self._global_monitor = (
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskKeyDown, global_handler
                )
            )
            self._local_monitor = (
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskKeyDown, local_handler
                )
            )
            return True
        except Exception as e:
            print(f"[hotkey] NSEvent monitor install failed: {e}")
            self.stop()
            return False

    def stop(self) -> None:
        try:
            from AppKit import NSEvent
        except Exception:
            return
        for m in (self._global_monitor, self._local_monitor):
            if m is not None:
                try:
                    NSEvent.removeMonitor_(m)
                except Exception:
                    pass
        self._global_monitor = None
        self._local_monitor = None


def _parse_mac_hotkey(spec: str) -> tuple[int, str]:
    """Parse pynput-style hotkey ("<ctrl>+<alt>+p") into (mods_mask, char).

    Returns the modifier-flag mask (device-independent) and the lowercase
    character that must be produced without modifiers.
    """
    from AppKit import (
        NSEventModifierFlagCommand,
        NSEventModifierFlagControl,
        NSEventModifierFlagOption,
        NSEventModifierFlagShift,
    )

    MOD_MAP = {
        "ctrl": NSEventModifierFlagControl,
        "control": NSEventModifierFlagControl,
        "alt": NSEventModifierFlagOption,
        "option": NSEventModifierFlagOption,
        "shift": NSEventModifierFlagShift,
        "cmd": NSEventModifierFlagCommand,
        "command": NSEventModifierFlagCommand,
    }

    mods = 0
    key_char: str | None = None
    for part in spec.split("+"):
        part = part.strip()
        if not part:
            continue
        if part.startswith("<") and part.endswith(">"):
            name = part[1:-1].lower()
            flag = MOD_MAP.get(name)
            if flag is None:
                raise ValueError(f"unknown modifier <{name}>")
            mods |= flag
        else:
            if key_char is not None:
                raise ValueError("only one non-modifier key allowed")
            if len(part) != 1:
                raise ValueError(f"expected single-char key, got '{part}'")
            key_char = part.lower()
    if key_char is None:
        raise ValueError("no key specified")
    return mods, key_char


# --- Windows / Linux: pynput ------------------------------------------------


class _PynputImpl:
    def __init__(self, hotkey: str, on_fire) -> None:
        self._hotkey = hotkey
        self._on_fire = on_fire
        self._listener = None

    def start(self) -> bool:
        try:
            from pynput import keyboard
        except Exception as e:
            print(f"[hotkey] pynput import failed: {e}")
            return False
        try:
            self._listener = keyboard.GlobalHotKeys(
                {self._hotkey: self._on_fire}
            )
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
