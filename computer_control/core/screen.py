"""Screenshots of the virtual desktop, a monitor, a window or a region (mss)."""
import base64
import io
import time
from datetime import datetime

import mss
from PIL import Image

from . import monitors, windows


def _grab(region: dict) -> Image.Image:
    with mss.mss() as sct:
        shot = sct.grab({"left": region["x"], "top": region["y"], "width": region["width"], "height": region["height"]})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _encode(img: Image.Image, max_width: int | None, fmt: str, quality: int) -> tuple[str, dict]:
    scale = 1.0
    if max_width and img.width > max_width:
        scale = max_width / img.width
        img = img.resize((max_width, max(1, round(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        mime = "image/jpeg"
    else:
        img.save(buf, "PNG", optimize=False)
        mime = "image/png"
    return base64.b64encode(buf.getvalue()).decode("ascii"), {
        "image_width": img.width, "image_height": img.height, "image_scale": round(scale, 4), "mime": mime,
        "bytes": buf.tell(),
    }


def capture(region: dict, label: str, max_width: int | None = 1600, fmt: str = "png", quality: int = 80, extra: dict | None = None) -> dict:
    img = _grab(region)
    data, meta = _encode(img, max_width, fmt, quality)
    act = windows.active_window()
    out = {
        "label": label,
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "region": region,  # desktop coords of the captured area, physical pixels
        "coordinate_note": "desktop_x = region.x + image_x / image_scale ; desktop_y = region.y + image_y / image_scale",
        "active_window": {k: act[k] for k in ("hwnd", "title", "process", "monitor_id")} if act else None,
        **meta,
        "image_base64": data,
    }
    if extra:
        out.update(extra)
    return out


def screenshot_desktop(max_width: int | None = 1600, fmt: str = "png", quality: int = 80) -> dict:
    vs = monitors.virtual_screen()
    return capture(vs, "virtual_desktop", max_width, fmt, quality, {"monitors": [
        {k: m[k] for k in ("id", "position", "x", "y", "width", "height", "scale", "primary")} for m in monitors.list_monitors()]})


def screenshot_monitor(monitor, max_width: int | None = 1600, fmt: str = "png", quality: int = 80) -> dict:
    m = monitors.resolve_monitor(monitor)
    region = {k: m[k] for k in ("x", "y", "width", "height")}
    return capture(region, f"monitor_{m['id']}", max_width, fmt, quality, {"monitor": {k: m[k] for k in ("id", "position", "scale", "primary")}})


def screenshot_window(ref, max_width: int | None = 1600, fmt: str = "png", quality: int = 80) -> dict:
    hwnd = windows.resolve(ref)
    info = windows.window_info(hwnd)
    if info["minimized"]:
        raise ValueError(f"window {info['title']!r} is minimized; restore/focus it first")
    b = info["bounds"]
    if b["width"] <= 0 or b["height"] <= 0:
        raise ValueError("window has no visible area")
    return capture(b, f"window_{hwnd}", max_width, fmt, quality, {"window": {k: info[k] for k in ("hwnd", "title", "process", "monitor_id")}})


def screenshot_region(x: int, y: int, width: int, height: int, max_width: int | None = None, fmt: str = "png", quality: int = 80) -> dict:
    return capture({"x": int(x), "y": int(y), "width": int(width), "height": int(height)}, "region", max_width, fmt, quality)


def wait_for_change(region: dict, timeout_s: float = 5.0, threshold: float = 0.002, interval_s: float = 0.25) -> dict:
    """Block until the region's pixels change by more than `threshold` fraction (or timeout)."""
    from PIL import ImageChops
    base = _grab(region).convert("L").resize((160, 90))
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(interval_s)
        cur = _grab(region).convert("L").resize((160, 90))
        diff = ImageChops.difference(base, cur)
        changed = sum(1 for p in diff.getdata() if p > 24) / (160 * 90)
        if changed > threshold:
            return {"changed": True, "fraction": round(changed, 4), "elapsed_s": round(time.time() - t0, 2)}
    return {"changed": False, "fraction": 0.0, "elapsed_s": round(time.time() - t0, 2)}
