r"""keybridge: turn bare keys into modifier combos, system-wide, for apps that refuse bare-key hotkeys.

Why: Wispr Flow requires a modifier in every shortcut, the Belkin n52te can only send single keys, and
Ctrl+Win (Wispr's default) collides with desktop switching. So every device (keyboard, G710 G-keys, n52te)
sends one plain key, and this bridge holds/taps the combo Wispr is configured for.

Run:  pythonw scripts\keybridge-launch.py   (scripts\install-keybridge.ps1 adds the logon task ComputerControlKeybridge)
Config: config\keybridge.json  ->  {"bindings": [{"vk": 36, "mode": "hold"}, "send": ["ctrl","alt","f9"], "name": "wispr push-to-talk"}, ...]}
  mode "hold": combo is pressed while the key is held, released when it is released.
  mode "tap":  combo is pressed+released once on key down.
The bare key is swallowed only when no modifier is held, so Shift+Insert etc. still work.
"""
import ctypes
from ctypes import wintypes
import json
import os
import time

from ..service.config import ROOT

CFG_PATH = os.path.join(ROOT, "config", "keybridge.json")
LOG = os.path.join(ROOT, "logs", "keybridge.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
DEFAULT = {"bindings": [
    {"name": "wispr push-to-talk", "vk": 0x24, "mode": "hold", "send": ["ctrl", "alt", "f9"]},   # Home (never Scroll Lock/Caps/Num: toggle keys show an OSD; Delete is used)
    {"name": "wispr hands-free", "vk": 0x2D, "mode": "tap", "send": ["ctrl", "alt", "f10"]},   # Insert
]}
MARK = 0xB19C  # dwExtraInfo on everything we inject, so our own events pass through the hook

# left-hand modifiers: Wispr stores shortcuts as LCtrl/LAlt (162/164)
VK = {"ctrl": 0xA2, "alt": 0xA4, "shift": 0xA0, "win": 0x5B, "space": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09}
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
VK.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
MODS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def load_cfg():
    if os.path.exists(CFG_PATH):
        return json.load(open(CFG_PATH, encoding="utf-8-sig"))
    json.dump(DEFAULT, open(CFG_PATH, "w", encoding="utf-8"), indent=2)
    return DEFAULT


user32 = ctypes.windll.user32
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def send(vks, down):
    seq = vks if down else list(reversed(vks))
    arr = (INPUT * len(seq))()
    for i, vk in enumerate(seq):
        arr[i].type = 1
        arr[i].ki = KEYBDINPUT(vk, 0, 0 if down else 2, 0, MARK)
    user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 13, 0x0100, 0x0101, 0x0104, 0x0105
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowsHookExW.restype = wintypes.HHOOK


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


def main():
    cfg = load_cfg()
    bindings = {int(b["vk"]): {"mode": b["mode"], "vks": [VK[k.lower()] for k in b["send"]], "name": b.get("name", "")} for b in cfg["bindings"]}
    held = set()

    def proc(n, wparam, lparam):
        if n >= 0:
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            b = bindings.get(k.vkCode)
            if b and k.dwExtraInfo != MARK:
                if k.vkCode not in held and any(user32.GetAsyncKeyState(m) & 0x8000 for m in MODS):
                    return user32.CallNextHookEx(None, n, wparam, lparam)  # modified press (Shift+Insert...) passes through
                if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if k.vkCode in held:
                        return 1  # autorepeat
                    held.add(k.vkCode)
                    if b["mode"] == "hold":
                        send(b["vks"], True)
                    else:
                        send(b["vks"], True); send(b["vks"], False)
                    log(f"{b['name']}: down")
                elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                    if k.vkCode in held:
                        held.discard(k.vkCode)
                        if b["mode"] == "hold":
                            send(b["vks"], False)
                        log(f"{b['name']}: up")
                return 1
        return user32.CallNextHookEx(None, n, wparam, lparam)

    cb = HOOKPROC(proc)
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, None, 0)
    if not hook:
        log("hook failed"); return
    log("keybridge up: " + ", ".join(f"vk{vk}->{b['name']}({b['mode']})" for vk, b in bindings.items()))
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
