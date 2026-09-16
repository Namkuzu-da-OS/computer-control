"""Top-level window management via Win32 (ctypes only)."""
import ctypes
from ctypes import wintypes
import os
import subprocess
import time
import re
import glob

from . import monitors
from . import input as inp

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.WindowFromPoint.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SW_RESTORE, SW_MINIMIZE, SW_MAXIMIZE, SW_SHOW = 9, 6, 3, 5
SWP_NOZORDER, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0004, 0x0001, 0x0002, 0x0010
WM_CLOSE = 0x0010
DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS = 14, 9
GW_OWNER = 4


def _text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _cloaked(hwnd) -> bool:
    v = wintypes.DWORD(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    return bool(v.value)


def _bounds(hwnd) -> dict:
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return {"x": r.left, "y": r.top, "width": r.right - r.left, "height": r.bottom - r.top}


def _process(hwnd) -> tuple[int, str]:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = buf.value
        finally:
            kernel32.CloseHandle(h)
    return pid.value, name


def window_info(hwnd: int) -> dict:
    hwnd = int(hwnd)
    if not user32.IsWindow(hwnd):
        raise ValueError(f"hwnd {hwnd} is not a window (it may have closed)")
    pid, exe = _process(hwnd)
    b = _bounds(hwnd)
    cx, cy = b["x"] + b["width"] // 2, b["y"] + b["height"] // 2
    mon = monitors.monitor_at(cx, cy)
    return {
        "hwnd": hwnd,
        "title": _text(hwnd),
        "class": _class(hwnd),
        "pid": pid,
        "exe": exe,
        "process": os.path.basename(exe) if exe else "",
        "bounds": b,
        "monitor_id": mon["id"] if mon else None,
        "monitor_position": mon["position"] if mon else None,
        "owner_hwnd": int(user32.GetWindow(hwnd, GW_OWNER) or 0) or None,  # set for dialogs owned by another window
        "minimized": bool(user32.IsIconic(hwnd)),
        "maximized": bool(user32.IsZoomed(hwnd)),
        "foreground": user32.GetForegroundWindow() == hwnd,
    }


def list_windows(include_untitled: bool = False) -> list[dict]:
    found: list[int] = []

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
            return True
        t = _text(hwnd)
        if not t and not include_untitled:
            return True
        found.append(hwnd)
        return True

    user32.EnumWindows(_EnumWindowsProc(cb), 0)
    out = []
    for h in found:
        try:
            out.append(window_info(h))
        except Exception:
            pass
    return out


def active_window() -> dict | None:
    h = user32.GetForegroundWindow()
    return window_info(h) if h else None


def window_at(x: int, y: int) -> dict | None:
    h = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not h:
        return None
    root = user32.GetAncestor(h, 2)  # GA_ROOT
    return window_info(root or h)


def find_windows(query: str) -> list[dict]:
    """Case-insensitive substring/regex match on title, process name or class."""
    q = query.lower()
    try:
        rx = re.compile(query, re.I)
    except re.error:
        rx = None
    hits = []
    for w in list_windows():
        hay = f"{w['title']} {w['process']} {w['class']}"
        if q in hay.lower() or (rx and rx.search(hay)):
            hits.append(w)
    return hits


def resolve(ref) -> int:
    """hwnd int, or a title/process query (best match = foreground first, then largest)."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return int(ref)
    hits = find_windows(str(ref))
    if not hits:
        raise ValueError(f"no window matches {ref!r}")
    hits.sort(key=lambda w: (not w["foreground"], w["minimized"], -(w["bounds"]["width"] * w["bounds"]["height"])))
    return hits[0]["hwnd"]


def focus(ref) -> dict:
    hwnd = resolve(ref)
    if not user32.IsWindowVisible(hwnd):  # e.g. an app parked in the tray with a hidden main window
        user32.ShowWindow(hwnd, SW_SHOW)
        time.sleep(0.15)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.15)
    if user32.GetForegroundWindow() == hwnd:
        return window_info(hwnd)
    # Windows refuses SetForegroundWindow unless the caller recently received input;
    # a harmless ALT tap plus thread-input attach is the standard, reliable workaround.
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
    inp.press("alt")
    attached = []
    for tid in {fg_tid, tgt_tid} - {0, cur_tid}:
        if user32.AttachThreadInput(cur_tid, tid, True):
            attached.append(tid)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.ShowWindow(hwnd, SW_SHOW)
    finally:
        for tid in attached:
            user32.AttachThreadInput(cur_tid, tid, False)
    for _ in range(10):
        if user32.GetForegroundWindow() == hwnd:
            break
        time.sleep(0.05)
    if user32.GetForegroundWindow() != hwnd:  # last resort: the Alt-Tab switcher path
        user32.SwitchToThisWindow(hwnd, True)
        time.sleep(0.2)
    info = window_info(hwnd)
    if not info["foreground"]:
        raise RuntimeError(f"could not bring hwnd {hwnd} ({info['title']!r}) to foreground; foreground is {_text(user32.GetForegroundWindow())!r}")
    return info


def move(ref, x: int, y: int) -> dict:
    hwnd = resolve(ref)
    if user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, SWP_NOZORDER | SWP_NOSIZE | SWP_NOACTIVATE)
    return window_info(hwnd)


def resize(ref, width: int, height: int) -> dict:
    hwnd = resolve(ref)
    if user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, None, 0, 0, int(width), int(height), SWP_NOZORDER | SWP_NOMOVE | SWP_NOACTIVATE)
    return window_info(hwnd)


def set_bounds(ref, x: int, y: int, width: int, height: int) -> dict:
    hwnd = resolve(ref)
    if user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, None, int(x), int(y), int(width), int(height), SWP_NOZORDER | SWP_NOACTIVATE)
    return window_info(hwnd)


def move_to_monitor(ref, monitor, maximize: bool = False) -> dict:
    hwnd = resolve(ref)
    m = monitors.resolve_monitor(monitor)
    was_max = bool(user32.IsZoomed(hwnd))
    if was_max:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
    b = _bounds(hwnd)
    wa = m["work_area"]
    w = min(b["width"], wa["width"])
    h = min(b["height"], wa["height"])
    x = wa["x"] + (wa["width"] - w) // 2
    y = wa["y"] + (wa["height"] - h) // 2
    user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(0.1)
    if maximize or was_max:
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    return window_info(hwnd)


def minimize(ref) -> dict:
    hwnd = resolve(ref)
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    return window_info(hwnd)


def maximize(ref) -> dict:
    hwnd = resolve(ref)
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    return window_info(hwnd)


def restore(ref) -> dict:
    hwnd = resolve(ref)
    user32.ShowWindow(hwnd, SW_RESTORE)
    return window_info(hwnd)


def close(ref) -> dict:
    hwnd = resolve(ref)
    info = window_info(hwnd)
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(0.3)
    info["closed"] = not bool(user32.IsWindow(hwnd))
    return info


# ---------------- launching ----------------

def _start_menu_lookup(name: str) -> str | None:
    roots = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    ]
    n = name.lower()
    best = None
    for root in roots:
        for p in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
            base = os.path.splitext(os.path.basename(p))[0].lower()
            if base == n:
                return p
            if n in base and (best is None or len(base) < len(os.path.basename(best))):
                best = p
    return best


def launch(target: str, args: str = "", wait_for_window_s: float = 8.0) -> dict:
    """target: exe path, exe name on PATH / App Paths, Start-Menu app name, URL or file."""
    before = {w["hwnd"] for w in list_windows()}
    launched_via = None
    t = os.path.expandvars(target)
    if os.path.exists(t) or re.match(r"^[a-z][a-z0-9+.-]*://", t, re.I):
        os.startfile(t) if not args else subprocess.Popen(f'"{t}" {args}', shell=True)
        launched_via = "startfile"
    else:
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-Command", f"Start-Process -FilePath '{t}'" + (f" -ArgumentList '{args}'" if args else "")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000)
            launched_via = "start-process"
        except Exception:
            pass
        lnk = _start_menu_lookup(t)
        if lnk and launched_via is None:
            os.startfile(lnk)
            launched_via = f"start-menu:{os.path.basename(lnk)}"
        elif lnk:
            launched_via += f" (start-menu candidate: {os.path.basename(lnk)})"
    deadline = time.time() + wait_for_window_s
    new = []
    while time.time() < deadline:
        time.sleep(0.4)
        new = [w for w in list_windows() if w["hwnd"] not in before]
        if new:
            break
    return {"target": target, "launched_via": launched_via, "new_windows": new}
