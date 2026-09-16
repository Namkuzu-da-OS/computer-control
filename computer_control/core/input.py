"""Mouse and keyboard via SendInput (ctypes only, no third-party deps).

All mouse coordinates are canonical virtual-desktop physical pixels; negative
values are valid (monitors left of / above the primary).
"""
import ctypes
from ctypes import wintypes
import time

from . import monitors  # noqa: F401  (forces DPI awareness before any cursor call)

user32 = ctypes.windll.user32
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004

_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _send(*inputs: INPUT) -> int:
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if n != len(inputs):
        raise OSError(f"SendInput sent {n}/{len(inputs)} (err {ctypes.GetLastError()})")
    return n


def _mouse(flags: int, data: int = 0) -> INPUT:
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, data, flags, 0, 0)
    return i


# ---------------- mouse ----------------

def cursor_position() -> dict:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return {"x": p.x, "y": p.y}


def move(x: int, y: int) -> dict:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    got = cursor_position()
    if abs(got["x"] - x) > 2 or abs(got["y"] - y) > 2:
        # cursor was clamped (off-screen target)
        raise ValueError(f"cursor landed at {got}, requested ({x},{y}) - is that point on a monitor?")
    return got


def click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1, hold_ms: int = 0) -> dict:
    if x is not None and y is not None:
        move(x, y)
    down, up = _BUTTONS[button]
    for i in range(clicks):
        _send(_mouse(down))
        if hold_ms:
            time.sleep(hold_ms / 1000)
        _send(_mouse(up))
        if i + 1 < clicks:
            time.sleep(0.06)
    return {"clicked": cursor_position(), "button": button, "clicks": clicks}


def mouse_down(button: str = "left") -> None:
    _send(_mouse(_BUTTONS[button][0]))


def mouse_up(button: str = "left") -> None:
    _send(_mouse(_BUTTONS[button][1]))


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_s: float = 0.4) -> dict:
    move(x1, y1)
    mouse_down(button)
    time.sleep(0.08)
    steps = max(8, int(duration_s / 0.02))
    for i in range(1, steps + 1):
        t = i / steps
        user32.SetCursorPos(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
        time.sleep(duration_s / steps)
    time.sleep(0.08)
    mouse_up(button)
    return {"from": {"x": x1, "y": y1}, "to": cursor_position()}


def scroll(amount: int, x: int | None = None, y: int | None = None, horizontal: bool = False) -> dict:
    """amount: positive = up (or right), negative = down (or left), in wheel notches."""
    if x is not None and y is not None:
        move(x, y)
    flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    step = 120 if amount > 0 else -120
    for _ in range(abs(int(amount))):
        _send(_mouse(flag, ctypes.c_uint32(step & 0xFFFFFFFF).value))
        time.sleep(0.03)
    return {"scrolled": amount, "horizontal": horizontal, "at": cursor_position()}


# ---------------- keyboard ----------------

VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10, "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21,
    "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E, "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "apps": 0x5D, "menu": 0x5D, "numlock": 0x90, "scrolllock": 0x91,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF, "medianext": 0xB0, "mediaprev": 0xB1,
    "mediastop": 0xB2, "playpause": 0xB3,
    "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63, "numpad4": 0x64, "numpad5": 0x65,
    "numpad6": 0x66, "numpad7": 0x67, "numpad8": 0x68, "numpad9": 0x69, "multiply": 0x6A, "add": 0x6B,
    "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC,
    "]": 0xDD, "'": 0xDE,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _c in "0123456789":
    VK[_c] = ord(_c)
_ALIASES = {"cmd": "win", "windows": "win", "super": "win", "command": "win", "option": "alt", "ret": "enter",
            "pgup": "pageup", "pgdn": "pagedown", "bs": "backspace", "ins": "insert", "plus": "=", "minus": "-"}
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90}


def vk_of(name: str) -> int:
    n = name.strip().lower()
    n = _ALIASES.get(n, n)
    if n in VK:
        return VK[n]
    if n.startswith("vk_") or n.startswith("0x"):
        return int(n.split("_")[-1], 16)
    raise ValueError(f"unknown key {name!r}")


def _key(vk: int, up: bool = False) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    scan = user32.MapVirtualKeyW(vk, 0)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def _unicode(code_unit: int, up: bool = False) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
    return i


def key_down(name: str) -> None:
    _send(_key(vk_of(name)))


def key_up(name: str) -> None:
    _send(_key(vk_of(name), up=True))


def press(name: str, times: int = 1, interval_s: float = 0.03) -> dict:
    vk = vk_of(name)
    for i in range(times):
        _send(_key(vk), _key(vk, up=True))
        if i + 1 < times:
            time.sleep(interval_s)
    return {"pressed": name, "times": times}


def hotkey(*names: str) -> dict:
    """hotkey('ctrl','shift','p') - also accepts a single 'ctrl+shift+p' string."""
    if len(names) == 1 and "+" in names[0] and len(names[0]) > 1:
        names = tuple(p for p in names[0].split("+") if p)
    vks = [vk_of(n) for n in names]
    try:
        for vk in vks:
            _send(_key(vk))
            time.sleep(0.02)
    finally:
        for vk in reversed(vks):
            _send(_key(vk, up=True))
            time.sleep(0.02)
    return {"hotkey": "+".join(names)}


def type_text(text: str, interval_s: float = 0.0) -> dict:
    """Types arbitrary Unicode. Newlines become Enter, tabs become Tab."""
    n = 0
    for ch in text:
        if ch == "\n":
            _send(_key(VK["enter"]), _key(VK["enter"], up=True))
        elif ch == "\r":
            continue
        elif ch == "\t":
            _send(_key(VK["tab"]), _key(VK["tab"], up=True))
        else:
            units = ch.encode("utf-16-le")
            for j in range(0, len(units), 2):
                cu = units[j] | (units[j + 1] << 8)
                _send(_unicode(cu), _unicode(cu, up=True))
        n += 1
        if interval_s:
            time.sleep(interval_s)
    return {"typed_chars": n}


def paste_text(text: str, restore_clipboard: bool = True) -> dict:
    """Clipboard insertion: safer for long or multi-line text."""
    import pyperclip
    old = None
    if restore_clipboard:
        try:
            old = pyperclip.paste()
        except Exception:
            old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    hotkey("ctrl", "v")
    time.sleep(0.15)
    if restore_clipboard and old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
    return {"pasted_chars": len(text)}
