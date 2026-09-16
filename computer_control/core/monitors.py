"""Monitor enumeration and the canonical coordinate system.

Canonical coordinates = Windows virtual-desktop PHYSICAL pixels. The process is
made per-monitor-DPI-aware at import so every rect, cursor position and
screenshot uses the same pixel grid, including monitors at negative offsets.
"""
import ctypes
from ctypes import wintypes
import re

user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore

_DPI_AWARE = False


def set_dpi_aware() -> bool:
    global _DPI_AWARE
    if _DPI_AWARE:
        return True
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _DPI_AWARE = True
            return True
    except Exception:
        pass
    try:
        if shcore.SetProcessDpiAwareness(2) == 0:
            _DPI_AWARE = True
            return True
    except Exception:
        pass
    _DPI_AWARE = bool(user32.SetProcessDPIAware())
    return _DPI_AWARE


set_dpi_aware()


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)


def _rect(r: wintypes.RECT) -> dict:
    return {"x": r.left, "y": r.top, "width": r.right - r.left, "height": r.bottom - r.top}


def virtual_screen() -> dict:
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
    return {
        "x": user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        "y": user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        "width": user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        "height": user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    }


def list_monitors() -> list[dict]:
    mons: list[dict] = []

    def cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        dpix, dpiy = wintypes.UINT(96), wintypes.UINT(96)
        try:
            shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpix), ctypes.byref(dpiy))
        except Exception:
            pass
        m = re.search(r"(\d+)$", mi.szDevice)
        mons.append({
            "id": int(m.group(1)) if m else len(mons) + 1,
            "device": mi.szDevice,
            "handle": int(hmon) if hmon else 0,
            "primary": bool(mi.dwFlags & 1),
            **_rect(mi.rcMonitor),
            "work_area": _rect(mi.rcWork),
            "scale": round(dpix.value / 96.0, 3),
        })
        return True

    user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(cb), 0)
    mons.sort(key=lambda m: m["id"])
    prim = next((m for m in mons if m["primary"]), mons[0] if mons else None)
    for m in mons:
        m["position"] = _position_label(m, prim)
        m["orientation"] = "portrait" if m["height"] > m["width"] else "landscape"
    return mons


def _position_label(m: dict, prim: dict | None) -> str:
    if prim is None or m is prim:
        return "primary"
    pcx, pcy = prim["x"] + prim["width"] / 2, prim["y"] + prim["height"] / 2
    cx, cy = m["x"] + m["width"] / 2, m["y"] + m["height"] / 2
    dx, dy = cx - pcx, cy - pcy
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "below" if dy > 0 else "above"


def monitor_by_id(monitor_id: int) -> dict:
    for m in list_monitors():
        if m["id"] == monitor_id:
            return m
    raise ValueError(f"no monitor with id {monitor_id}")


def monitor_at(x: int, y: int) -> dict | None:
    for m in list_monitors():
        if m["x"] <= x < m["x"] + m["width"] and m["y"] <= y < m["y"] + m["height"]:
            return m
    return None


def resolve_monitor(ref) -> dict:
    """Accept an id (int), a position word ('left','right','above','below','primary') or a device name."""
    mons = list_monitors()
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return monitor_by_id(int(ref))
    if isinstance(ref, str):
        r = ref.lower().strip()
        aliases = {"upper": "above", "top": "above", "lower": "below", "bottom": "below", "main": "primary", "center": "primary", "middle": "primary"}
        r = aliases.get(r, r)
        for m in mons:
            if m["position"] == r or m["device"].lower() == r:
                return m
    raise ValueError(f"cannot resolve monitor {ref!r}; have " + ", ".join(f"{m['id']}={m['position']}" for m in mons))
