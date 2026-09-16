"""Windows UI Automation (via the `uiautomation` package, which wraps the native
UIA COM API). Semantic access to buttons, tabs, menus, text fields, etc.

Elements returned by inspect/find carry a short `id` (e.g. "e17") valid until the
next inspect/find call; actions accept that id OR a (name, control_type) query.
"""
import time
import re

import uiautomation as auto

from . import windows, input as inp

auto.SetGlobalSearchTimeout(2.0)
try:
    auto.Logger.SetLogFile("")  # silence the package's own log file
except Exception:
    pass

_cache: dict[str, auto.Control] = {}
_cache_seq = 0

_TYPE_ALIASES = {
    "button": "ButtonControl", "tab": "TabItemControl", "tabitem": "TabItemControl", "tabs": "TabControl",
    "text": "TextControl", "edit": "EditControl", "textbox": "EditControl", "field": "EditControl", "input": "EditControl",
    "checkbox": "CheckBoxControl", "radio": "RadioButtonControl", "radiobutton": "RadioButtonControl",
    "combobox": "ComboBoxControl", "dropdown": "ComboBoxControl", "list": "ListControl", "listitem": "ListItemControl",
    "item": "ListItemControl", "menu": "MenuControl", "menuitem": "MenuItemControl", "menubar": "MenuBarControl",
    "tree": "TreeControl", "treeitem": "TreeItemControl", "hyperlink": "HyperlinkControl", "link": "HyperlinkControl",
    "slider": "SliderControl", "window": "WindowControl", "pane": "PaneControl", "image": "ImageControl",
    "group": "GroupControl", "document": "DocumentControl", "toolbar": "ToolBarControl", "custom": "CustomControl",
    "scrollbar": "ScrollBarControl", "spinner": "SpinnerControl", "splitbutton": "SplitButtonControl",
    "table": "TableControl", "dataitem": "DataItemControl", "header": "HeaderControl", "statusbar": "StatusBarControl",
    "progressbar": "ProgressBarControl", "titlebar": "TitleBarControl", "separator": "SeparatorControl",
}
_NOISE_TYPES = {"PaneControl", "GroupControl", "CustomControl", "ImageControl", "SeparatorControl"}


def _norm_type(t: str | None) -> str | None:
    if not t:
        return None
    k = t.replace(" ", "").replace("_", "").lower()
    if k.endswith("control"):
        k = k[:-7]
    return _TYPE_ALIASES.get(k, t if t.endswith("Control") else t.capitalize() + "Control")


def _short_type(c: auto.Control) -> str:
    return c.ControlTypeName.replace("Control", "")


def _node(c: auto.Control, eid: str, depth: int) -> dict:
    r = c.BoundingRectangle
    d = {
        "id": eid, "type": _short_type(c), "name": c.Name or "", "depth": depth,
        "rect": {"x": r.left, "y": r.top, "width": r.width(), "height": r.height()},
        "center": {"x": (r.left + r.right) // 2, "y": (r.top + r.bottom) // 2},
    }
    if c.AutomationId:
        d["automation_id"] = c.AutomationId
    if c.ClassName:
        d["class"] = c.ClassName
    if not c.IsEnabled:
        d["enabled"] = False
    if c.IsOffscreen:
        d["offscreen"] = True
    try:
        vp = c.GetValuePattern() if hasattr(c, "GetValuePattern") else None
        if vp is not None:
            d["value"] = vp.Value
    except Exception:
        pass
    try:
        tp = c.GetTogglePattern() if hasattr(c, "GetTogglePattern") else None
        if tp is not None:
            d["toggled"] = tp.ToggleState == 1
    except Exception:
        pass
    try:
        sp = c.GetSelectionItemPattern() if hasattr(c, "GetSelectionItemPattern") else None
        if sp is not None:
            d["selected"] = bool(sp.IsSelected)
    except Exception:
        pass
    try:
        ep = c.GetExpandCollapsePattern() if hasattr(c, "GetExpandCollapsePattern") else None
        if ep is not None:
            d["expanded"] = ep.ExpandCollapseState == 1
    except Exception:
        pass
    return d


def _root(window_ref=None) -> auto.Control:
    if window_ref is None:
        return auto.GetRootControl()
    hwnd = windows.resolve(window_ref)
    return auto.ControlFromHandle(hwnd)


def _remember(c: auto.Control) -> str:
    global _cache_seq
    _cache_seq += 1
    eid = f"e{_cache_seq}"
    _cache[eid] = c
    return eid


def _walk(root: auto.Control, max_depth: int, max_nodes: int):
    """Breadth-limited DFS yielding (control, depth)."""
    n = 0
    stack = [(root, 0)]
    while stack and n < max_nodes:
        c, d = stack.pop()
        yield c, d
        n += 1
        if d < max_depth:
            try:
                kids = c.GetChildren()
            except Exception:
                kids = []
            for k in reversed(kids):
                stack.append((k, d + 1))


def inspect(window_ref=None, max_depth: int = 40, max_nodes: int = 400, include_noise: bool = False,
            only_visible: bool = True) -> dict:
    """Interactive UI tree of a window (default: foreground window)."""
    global _cache
    if window_ref is None:
        aw = windows.active_window()
        window_ref = aw["hwnd"] if aw else None
    root = _root(window_ref)
    _cache = {}
    nodes = _collect(root, max_depth, max_nodes, include_noise, only_visible)
    if len(nodes) < 8:
        # Chromium/Electron apps switch accessibility on lazily at the first UIA query; give them a beat.
        time.sleep(0.6)
        _cache = {}
        nodes = _collect(root, max_depth, max_nodes, include_noise, only_visible)
    return {"window": windows.window_info(windows.resolve(window_ref)) if window_ref else None,
            "count": len(nodes), "truncated": len(nodes) >= max_nodes, "elements": nodes}


def _collect(root, max_depth, max_nodes, include_noise, only_visible) -> list[dict]:
    nodes = []
    for c, d in _walk(root, max_depth, max_nodes * 4):
        try:
            t = c.ControlTypeName
            if only_visible and c.IsOffscreen and d > 0:
                continue
            if not include_noise and t in _NOISE_TYPES and not c.Name and not c.AutomationId:
                continue
            if not include_noise and t == "TextControl" and not c.Name:
                continue
            nodes.append(_node(c, _remember(c), d))
            if len(nodes) >= max_nodes:
                break
        except Exception:
            continue
    return nodes


def find(name: str | None = None, control_type: str | None = None, window_ref=None, automation_id: str | None = None,
         exact: bool = False, max_results: int = 20, max_depth: int = 30) -> dict:
    """Find elements by (substring or regex) name and/or control type within a window (default foreground)."""
    global _cache
    if window_ref is None:
        aw = windows.active_window()
        window_ref = aw["hwnd"] if aw else None
    root = _root(window_ref)
    ctype = _norm_type(control_type)
    rx = None
    if name and not exact:
        try:
            rx = re.compile(name, re.I)
        except re.error:
            rx = None
    _cache = {}
    hits = []
    for c, d in _walk(root, max_depth, 20000):
        try:
            if ctype and c.ControlTypeName != ctype:
                continue
            if automation_id and c.AutomationId != automation_id:
                continue
            if name:
                n = c.Name or ""
                if exact:
                    if n.lower() != name.lower():
                        continue
                elif name.lower() not in n.lower() and not (rx and rx.search(n)):
                    continue
            hits.append(_node(c, _remember(c), d))
            if len(hits) >= max_results:
                break
        except Exception:
            continue
    return {"count": len(hits), "elements": hits}


def _get(element) -> auto.Control:
    """element: cached id 'e12' | dict with 'id' | name string (searched in foreground window)."""
    if isinstance(element, dict):
        element = element.get("id") or element.get("name")
    if isinstance(element, str) and element in _cache:
        c = _cache[element]
        try:
            if c.Exists(0, 0):
                return c
        except Exception:
            pass
        raise ValueError(f"element {element} is stale (UI changed); inspect/find again")
    res = find(name=str(element), max_results=5)
    els = [e for e in res["elements"] if e["type"] not in ("Text",)] or res["elements"]
    if not els:
        raise ValueError(f"no element named {element!r} found in the foreground window")
    return _cache[els[0]["id"]]


def _ensure_foreground(c: auto.Control) -> None:
    try:
        top = c.GetTopLevelControl()
        hwnd = top.NativeWindowHandle if top else 0
        if hwnd and windows.user32.GetForegroundWindow() != hwnd:
            windows.focus(hwnd)
    except Exception:
        pass


def click_element(element, method: str = "auto", button: str = "left") -> dict:
    """auto: try UIA patterns (Invoke/Toggle/Select/Expand/LegacyDefaultAction) then fall back to a real mouse click at center."""
    c = _get(element)
    before = _node(c, "x", 0)
    _ensure_foreground(c)
    used = None
    if method in ("auto", "pattern") and button == "left":
        for attempt in ("Invoke", "Toggle", "SelectionItem", "ExpandCollapse", "Legacy"):
            try:
                if attempt == "Invoke":
                    p = c.GetInvokePattern()
                    if p: p.Invoke(); used = "InvokePattern"; break
                elif attempt == "Toggle":
                    p = c.GetTogglePattern()
                    if p: p.Toggle(); used = "TogglePattern"; break
                elif attempt == "SelectionItem":
                    p = c.GetSelectionItemPattern()
                    if p: p.Select(); used = "SelectionItemPattern"; break
                elif attempt == "ExpandCollapse":
                    p = c.GetExpandCollapsePattern()
                    if p:
                        p.Expand() if p.ExpandCollapseState != 1 else p.Collapse(); used = "ExpandCollapsePattern"; break
                elif attempt == "Legacy":
                    p = c.GetLegacyIAccessiblePattern()
                    if p and p.DefaultAction:
                        p.DoDefaultAction(); used = "LegacyIAccessible:" + p.DefaultAction; break
            except Exception:
                continue
    if used is None:
        if method == "pattern":
            raise RuntimeError("element exposes no invokable UIA pattern; use method='mouse'")
        r = c.BoundingRectangle
        if r.width() <= 0 or r.height() <= 0:
            raise RuntimeError("element has no on-screen bounds to click")
        inp.click((r.left + r.right) // 2, (r.top + r.bottom) // 2, button=button)
        used = "mouse"
    time.sleep(0.15)
    return {"method": used, "element": before}


def set_text(element, value: str, method: str = "auto") -> dict:
    c = _get(element)
    _ensure_foreground(c)
    if method in ("auto", "pattern"):
        try:
            p = c.GetValuePattern()
            if p and not p.IsReadOnly:
                p.SetValue(value)
                time.sleep(0.1)
                return {"method": "ValuePattern", "value": c.GetValuePattern().Value}
        except Exception:
            if method == "pattern":
                raise
    try:
        c.SetFocus()
    except Exception:
        r = c.BoundingRectangle
        inp.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.05)
    inp.hotkey("ctrl", "a")
    inp.paste_text(value) if len(value) > 40 or "\n" in value else inp.type_text(value)
    return {"method": "keyboard", "chars": len(value)}


def focus_element(element) -> dict:
    c = _get(element)
    _ensure_foreground(c)
    c.SetFocus()
    return _node(c, "x", 0)


def toggle(element, state: bool | None = None) -> dict:
    c = _get(element)
    _ensure_foreground(c)
    p = c.GetTogglePattern()
    if p is None:
        return click_element(element)
    cur = p.ToggleState == 1
    if state is None or cur != state:
        p.Toggle()
        time.sleep(0.1)
    return {"toggled": c.GetTogglePattern().ToggleState == 1}


def select(element) -> dict:
    c = _get(element)
    _ensure_foreground(c)
    p = c.GetSelectionItemPattern()
    if p is None:
        return click_element(element)
    p.Select()
    return {"selected": bool(c.GetSelectionItemPattern().IsSelected)}


def expand(element, expand: bool = True) -> dict:
    c = _get(element)
    _ensure_foreground(c)
    p = c.GetExpandCollapsePattern()
    if p is None:
        return click_element(element)
    p.Expand() if expand else p.Collapse()
    return {"expanded": c.GetExpandCollapsePattern().ExpandCollapseState == 1}


def element_at(x: int, y: int) -> dict:
    c = auto.ControlFromPoint(int(x), int(y))
    if c is None:
        raise ValueError("no UIA element at that point")
    _cache.clear()
    d = _node(c, _remember(c), 0)
    path = []
    p = c.GetParentControl()
    while p is not None and len(path) < 6:
        if p.Name:
            path.append(f"{_short_type(p)}:{p.Name}")
        p = p.GetParentControl()
    d["ancestors"] = path
    return d


def focused_element() -> dict:
    c = auto.GetFocusedControl()
    if c is None:
        raise ValueError("nothing focused")
    _cache.clear()
    return _node(c, _remember(c), 0)


def wait_for(name: str, control_type: str | None = None, window_ref=None, timeout_s: float = 8.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        r = find(name=name, control_type=control_type, window_ref=window_ref, max_results=1)
        if r["count"]:
            return {"found": True, "elapsed_s": round(time.time() - t0, 2), "element": r["elements"][0]}
        time.sleep(0.3)
    return {"found": False, "elapsed_s": round(time.time() - t0, 2)}
