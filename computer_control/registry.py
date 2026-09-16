"""The single tool table. Every adapter (REST, MCP, future OpenAI function-calling)
derives its tool list and JSON schemas from here. Nothing else defines tools.

All tool calls run on ONE dedicated worker thread (COM-initialised for UIA) so
input events never interleave and the UIA client is always on a valid thread.
"""
import inspect as _inspect
import subprocess
import types
import typing
from concurrent.futures import ThreadPoolExecutor

from .core import monitors, input as inp, windows, screen, uia, safety

TOOLS: dict[str, dict] = {}


def _schema_for(fn) -> dict:
    sig = _inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for name, p in sig.parameters.items():
        t = hints.get(name, str)
        origin = typing.get_origin(t)
        is_union = origin is typing.Union or origin is types.UnionType
        args = [a for a in typing.get_args(t) if a is not type(None)]
        optional = is_union and len(args) < len(typing.get_args(t))
        base = args[0] if (is_union and args) else t
        js = {int: "integer", float: "number", bool: "boolean", str: "string", list: "array", dict: "object"}.get(base, "string")
        if typing.get_origin(base) is list:
            js = "array"
        prop = {"type": js}
        if optional or p.default is not _inspect.Parameter.empty:
            if p.default is not _inspect.Parameter.empty and p.default is not None:
                prop["default"] = p.default
        else:
            required.append(name)
        props[name] = prop
    return {"type": "object", "properties": props, "required": required}


def tool(description: str, returns_image: bool = False):
    def deco(fn):
        TOOLS[fn.__name__] = {"name": fn.__name__, "description": description, "fn": fn,
                              "schema": _schema_for(fn), "returns_image": returns_image}
        return fn
    return deco


# ============ observation ============

@tool("List monitors: id, position word (primary/left/right/above/below), bounds in desktop pixels, DPI scale. Coordinates may be negative.")
def list_monitors() -> dict:
    return {"virtual_screen": monitors.virtual_screen(), "monitors": [{k: v for k, v in m.items() if k != "handle"} for m in monitors.list_monitors()]}


@tool("Screenshot of the whole virtual desktop (all monitors). Downscaled to max_width; use region.x/y + image_scale to map image pixels back to desktop coords.", returns_image=True)
def get_screenshot(max_width: int = 1600, format: str = "png") -> dict:
    return screen.screenshot_desktop(max_width, format)


@tool("Screenshot of one monitor. `monitor` = id number or position word (primary, left, right, above, below).", returns_image=True)
def get_monitor_screenshot(monitor: str, max_width: int = 1600, format: str = "png") -> dict:
    return screen.screenshot_monitor(monitor, max_width, format)


@tool("Screenshot of one window (default: the active window). `window` = hwnd or title/process substring.", returns_image=True)
def get_window_screenshot(window: str | None = None, max_width: int = 1600, format: str = "png") -> dict:
    if window is None:
        aw = windows.active_window()
        window = aw["hwnd"] if aw else None
    return screen.screenshot_window(window, max_width, format)


@tool("Screenshot of a rectangular desktop region at full resolution (good for reading small text after a wide shot).", returns_image=True)
def get_region_screenshot(x: int, y: int, width: int, height: int, max_width: int | None = None) -> dict:
    return screen.screenshot_region(x, y, width, height, max_width)


@tool("The foreground window: hwnd, title, process, bounds, which monitor.")
def get_active_window() -> dict:
    return windows.active_window() or {"active_window": None}


@tool("All visible top-level windows with title, process, bounds, monitor, minimized/maximized state.")
def list_windows() -> dict:
    return {"windows": windows.list_windows()}


@tool("Find windows whose title/process/class matches a substring or regex.")
def find_window(query: str) -> dict:
    return {"windows": windows.find_windows(query)}


@tool("Details for one window. `window` = hwnd or a title/process substring.")
def get_window_info(window: str) -> dict:
    return windows.window_info(windows.resolve(window))


@tool("Current mouse cursor position in desktop coordinates, plus which monitor and window is under it.")
def get_cursor_position() -> dict:
    p = inp.cursor_position()
    m = monitors.monitor_at(p["x"], p["y"])
    w = windows.window_at(p["x"], p["y"])
    return {**p, "monitor_id": m["id"] if m else None, "window": {k: w[k] for k in ("hwnd", "title", "process")} if w else None}


# ============ UI Automation ============

@tool("UI Automation tree of a window (default: active window): buttons, tabs, edits, menus, list items with names, types, on-screen rects and element ids. Prefer this over screenshots when the app exposes accessibility.")
def inspect_ui(window: str | None = None, max_depth: int = 40, max_nodes: int = 400, include_noise: bool = False) -> dict:
    return uia.inspect(window, max_depth, max_nodes, include_noise)


@tool("Find UI elements by name (substring/regex) and/or control type (button, tab, edit, checkbox, menuitem, listitem, link...). Returns element ids usable by click_element/set_text.")
def find_ui_element(name: str | None = None, control_type: str | None = None, window: str | None = None,
                    automation_id: str | None = None, exact: bool = False, max_results: int = 20) -> dict:
    return uia.find(name, control_type, window, automation_id, exact, max_results)


@tool("Wait up to timeout_s for a UI element with this name to appear (verification after an action).")
def wait_for_element(name: str, control_type: str | None = None, window: str | None = None, timeout_s: float = 8.0) -> dict:
    return uia.wait_for(name, control_type, window, timeout_s)


@tool("The UIA element under a desktop point, with its ancestor path (what is that thing at x,y?).")
def get_element_at(x: int, y: int) -> dict:
    return uia.element_at(x, y)


@tool("The UIA element that currently has keyboard focus.")
def get_focused_element() -> dict:
    return uia.focused_element()


@tool("Click a UI element semantically. `element` = id from inspect/find (e.g. 'e12') or a name to search in the active window. method: auto (UIA pattern then mouse), pattern, mouse.")
def click_element(element: str, method: str = "auto", button: str = "left") -> dict:
    return uia.click_element(element, method, button)


@tool("Set the text of an edit/combobox element (UIA ValuePattern, else select-all + type/paste).")
def set_text(element: str, value: str, method: str = "auto") -> dict:
    return uia.set_text(element, value, method)


@tool("Give keyboard focus to a UI element.")
def focus_element(element: str) -> dict:
    return uia.focus_element(element)


@tool("Toggle a checkbox/switch. state=true/false to force, omit to flip.")
def toggle_checkbox(element: str, state: bool | None = None) -> dict:
    return uia.toggle(element, state)


@tool("Select a list item / tab item / radio button / menu item by element id or name.")
def select_item(element: str) -> dict:
    return uia.select(element)


@tool("Expand (or collapse) a dropdown, combo box, tree node or menu.")
def expand_element(element: str, expand: bool = True) -> dict:
    return uia.expand(element, expand)


# ============ mouse ============

@tool("Move the mouse to desktop coordinates (negative values allowed for monitors left/above primary).")
def move_mouse(x: int, y: int) -> dict:
    return inp.move(x, y)


@tool("Click at desktop coordinates (or at the current cursor if omitted). button: left/right/middle.")
def click(x: int | None = None, y: int | None = None, button: str = "left") -> dict:
    return inp.click(x, y, button)


@tool("Double-click at desktop coordinates.")
def double_click(x: int | None = None, y: int | None = None) -> dict:
    return inp.click(x, y, "left", clicks=2)


@tool("Right-click at desktop coordinates.")
def right_click(x: int | None = None, y: int | None = None) -> dict:
    return inp.click(x, y, "right")


@tool("Press-and-hold drag from (x1,y1) to (x2,y2).")
def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_s: float = 0.4) -> dict:
    return inp.drag(x1, y1, x2, y2, button, duration_s)


@tool("Scroll the wheel. amount in notches: negative = down, positive = up. Optionally move to x,y first. horizontal=true for sideways.")
def scroll(amount: int, x: int | None = None, y: int | None = None, horizontal: bool = False) -> dict:
    return inp.scroll(amount, x, y, horizontal)


# ============ keyboard ============

@tool("Type arbitrary text into the focused control (Unicode safe; \\n = Enter, \\t = Tab). Use paste_text for long/multi-line text.")
def type_text(text: str, interval_s: float = 0.0) -> dict:
    return inp.type_text(text, interval_s)


@tool("Insert text via clipboard (Ctrl+V) - fastest and safest for long or multi-line text. Clipboard is restored afterwards.")
def paste_text(text: str) -> dict:
    return inp.paste_text(text)


@tool("Press a key by name: enter, tab, esc, backspace, delete, up/down/left/right, home, end, pageup, pagedown, f1-f24, win, space, a-z, 0-9...")
def press_key(key: str, times: int = 1) -> dict:
    return inp.press(key, times)


@tool("Press a key combination, e.g. 'ctrl+shift+p', 'alt+f4', 'win+d', 'ctrl+c'.")
def hotkey(keys: str) -> dict:
    return inp.hotkey(keys)


@tool("Hold a key down (remember to key_up).")
def key_down(key: str) -> dict:
    inp.key_down(key); return {"down": key}


@tool("Release a held key.")
def key_up(key: str) -> dict:
    inp.key_up(key); return {"up": key}


# ============ windows ============

@tool("Bring a window to the foreground (restores if minimized). `window` = hwnd or title/process substring, e.g. 'Logi Options' or 'chrome'.")
def focus_window(window: str) -> dict:
    return windows.focus(window)


@tool("Move a window's top-left corner to desktop x,y.")
def move_window(window: str, x: int, y: int) -> dict:
    return windows.move(window, x, y)


@tool("Move a window onto another monitor (id or position word: left/right/above/below/primary), centred and clamped to fit. maximize=true to fill it.")
def move_window_to_monitor(window: str, monitor: str, maximize: bool = False) -> dict:
    return windows.move_to_monitor(window, monitor, maximize)


@tool("Resize a window.")
def resize_window(window: str, width: int, height: int) -> dict:
    return windows.resize(window, width, height)


@tool("Set a window's exact bounds.")
def set_window_bounds(window: str, x: int, y: int, width: int, height: int) -> dict:
    return windows.set_bounds(window, x, y, width, height)


@tool("Minimize a window.")
def minimize_window(window: str) -> dict:
    return windows.minimize(window)


@tool("Maximize a window.")
def maximize_window(window: str) -> dict:
    return windows.maximize(window)


@tool("Restore a window from minimized/maximized.")
def restore_window(window: str) -> dict:
    return windows.restore(window)


@tool("Close a window politely (WM_CLOSE; the app may prompt to save).")
def close_window(window: str) -> dict:
    return windows.close(window)


@tool("Launch an application by exe path, exe name, Start Menu name (e.g. 'Logi Options+', 'Settings', 'Notepad'), URL or file. Waits for a new window and returns it.")
def launch_application(target: str, args: str = "", wait_for_window_s: float = 8.0) -> dict:
    return windows.launch(target, args, wait_for_window_s)


# ============ shell ============

@tool("Run a PowerShell command locally and return stdout/stderr/exit code. Destructive commands (format, diskpart, wipe user dirs, shutdown...) return confirmation_required; re-run with confirm=<token> after the user says yes.")
def run_powershell(command: str, timeout_s: float = 120.0, confirm: str | None = None) -> dict:
    g = safety.gate(command, confirm)
    if g:
        return g
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True,
                       text=True, timeout=timeout_s, creationflags=0x08000000)
    return {"exit_code": p.returncode, "stdout": p.stdout[-20000:], "stderr": p.stderr[-5000:]}


@tool("Block until the pixels of a desktop region change (or timeout). Use after an action to confirm the UI reacted.")
def wait_for_screen_change(x: int, y: int, width: int, height: int, timeout_s: float = 5.0) -> dict:
    return screen.wait_for_change({"x": x, "y": y, "width": width, "height": height}, timeout_s)


# ============ executor ============

def _init_thread():
    import comtypes
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    except Exception:
        pass
    monitors.set_dpi_aware()


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cc-worker", initializer=_init_thread)


def call(name: str, args: dict):
    t = TOOLS.get(name)
    if not t:
        raise KeyError(f"unknown tool {name!r}")
    args = {k: v for k, v in (args or {}).items() if v is not None}
    return _executor.submit(t["fn"], **args).result(timeout=300)


def specs(include_fn: bool = False) -> list[dict]:
    return [{k: v for k, v in t.items() if include_fn or k != "fn"} for t in TOOLS.values()]
