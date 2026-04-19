import sys


def find_game_window_id(title: str) -> int | None:
    """Return the macOS CGWindowID for the named window (w>200, h>200), or None."""
    try:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
        )
        for win in windows:
            owner = str(win.get(Quartz.kCGWindowOwnerName, ""))
            name = str(win.get(Quartz.kCGWindowName, ""))
            if owner != title and name != title:
                continue
            b = win.get(Quartz.kCGWindowBounds, {})
            if int(b.get("Width", 0)) > 200 and int(b.get("Height", 0)) > 200:
                return win.get(Quartz.kCGWindowNumber)
    except Exception as e:
        print(f"[window_finder] find_game_window_id error: {e}")
    return None


def find_window_client_rect(title: str) -> tuple[int, int, int, int] | None:
    """Return (x, y, width, height) of the client area for the named window, or None."""
    if sys.platform == "darwin":
        return _find_mac(title)
    if sys.platform == "win32":
        return _find_windows(title)
    return _find_linux(title)


def _find_mac(title: str) -> tuple[int, int, int, int] | None:
    # Pass 1: Accessibility API via osascript (fast, accurate)
    import subprocess
    script = f'''
tell application "System Events"
    tell process "{title}"
        set win to window 1
        set p to position of win
        set s to size of win
        return p & s
    end tell
end tell
'''
    try:
        result = subprocess.check_output(["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL).strip()
        if result:
            parts = [int(x.strip()) for x in result.split(",")]
            if len(parts) == 4:
                x, y, w, h = parts
                title_bar = 28
                if h > title_bar:
                    return (x, y + title_bar, w, h - title_bar)
    except subprocess.CalledProcessError:
        pass

    # Pass 2: Quartz window server (works for Metal/OpenGL games that skip Accessibility)
    try:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll,
            Quartz.kCGNullWindowID,
        )
        for win in windows:
            owner = str(win.get(Quartz.kCGWindowOwnerName, ""))
            name = str(win.get(Quartz.kCGWindowName, ""))
            if owner != title and name != title:
                continue
            b = win.get(Quartz.kCGWindowBounds)
            if not b:
                continue
            x, y = int(b.get("X", 0)), int(b.get("Y", 0))
            w, h = int(b.get("Width", 0)), int(b.get("Height", 0))
            if w > 200 and h > 200:
                title_bar = 28
                if h > title_bar:
                    return (x, y + title_bar, w, h - title_bar)
    except Exception as e:
        print(f"[window_finder] macOS Quartz error: {e}")

    return None


def _find_windows(title: str) -> tuple[int, int, int, int] | None:
    try:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return None
        rect = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 0 and h > 0:
            return (pt.x, pt.y, w, h)
    except Exception as e:
        print(f"[window_finder] Windows error: {e}")
    return None


def _find_linux(title: str) -> tuple[int, int, int, int] | None:
    try:
        import subprocess
        result = subprocess.run(
            ["xdotool", "search", "--name", title],
            capture_output=True, text=True, timeout=2,
        )
        wids = result.stdout.strip().split()
        if not wids:
            return None
        geo = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", wids[0]],
            capture_output=True, text=True, timeout=2,
        )
        info = {}
        for line in geo.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k] = v
        x = int(info.get("X", 0))
        y = int(info.get("Y", 0))
        w = int(info.get("WIDTH", 0))
        h = int(info.get("HEIGHT", 0))
        if w > 0 and h > 0:
            return (x, y, w, h)
    except Exception:
        pass
    return None
