"""JSONL activity log: timestamp, client, tool, args (redacted), result summary, error."""
import json
import os
import threading
from datetime import datetime

LOG_DIR = os.environ.get("CC_LOG_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
_lock = threading.Lock()

_REDACT = {"type_text": ["text"], "paste_text": ["text"], "set_text": ["value"], "run_powershell": []}


def _redact(tool: str, args: dict) -> dict:
    out = {}
    for k, v in (args or {}).items():
        if k in _REDACT.get(tool, []) and isinstance(v, str):
            out[k] = f"<{len(v)} chars>"
        elif isinstance(v, str) and len(v) > 300:
            out[k] = v[:300] + "..."
        else:
            out[k] = v
    return out


def _summarize(result) -> object:
    if isinstance(result, dict):
        r = {k: v for k, v in result.items() if k != "image_base64"}
        if "image_base64" in result:
            r["image_base64"] = f"<{len(result['image_base64'])} b64 chars>"
        if "elements" in r and isinstance(r["elements"], list):
            r["elements"] = f"<{len(r['elements'])} elements>"
        return r
    return result


def record(client: str, tool: str, args: dict, result=None, error: str | None = None, ms: float | None = None) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "client": client or "unknown",
        "tool": tool,
        "args": _redact(tool, args),
        "ms": round(ms, 1) if ms is not None else None,
    }
    if error:
        entry["error"] = error
    else:
        entry["result"] = _summarize(result)
    path = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".jsonl")
    line = json.dumps(entry, ensure_ascii=False, default=str)
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
