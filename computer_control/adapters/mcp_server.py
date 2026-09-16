"""MCP (stdio) adapter. A thin proxy: fetches the tool list from the REST
service and re-exposes every tool 1:1. Contains NO control logic.

Used identically by Claude Code and Codex (both speak MCP over stdio):
    <venv>\\python.exe -m computer_control.adapters.mcp_server [--client NAME]

If the service is not running it is started (detached) automatically.
Requires the `mcp` Python SDK 2.x (MCPServer API).
"""
import argparse
import asyncio
import inspect
import json
import os
import subprocess
import sys
import time
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent, ImageContent

from ..service.config import load_config, base_url, ROOT

CFG = load_config()
BASE = base_url(CFG)
HEADERS = {"X-CC-Token": CFG["token"]}
_PY = {"integer": int, "number": float, "boolean": bool, "string": str, "array": list, "object": dict}


def _service_up() -> bool:
    try:
        return httpx.get(BASE + "/health", timeout=1.5).status_code == 200
    except Exception:
        return False


def ensure_service():
    if _service_up():
        return
    py = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(py):
        py = sys.executable
    subprocess.Popen([py, "-m", "computer_control.service.app"], cwd=ROOT,
                     creationflags=0x00000008 | 0x00000200 | 0x08000000,  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    for _ in range(40):
        time.sleep(0.25)
        if _service_up():
            return
    raise RuntimeError("computer-control service failed to start; run scripts/start-service.ps1 and check logs/")


def _content(result: Any) -> list:
    if isinstance(result, dict) and "image_base64" in result:
        meta = {k: v for k, v in result.items() if k != "image_base64"}
        return [ImageContent(type="image", data=result["image_base64"], mimeType=result.get("mime", "image/png")),
                TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))]
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


def _make_proxy(spec: dict, client_name: str):
    name = spec["name"]
    props = spec["schema"]["properties"]
    required = set(spec["schema"]["required"])

    async def proxy(**kwargs):
        def _do():
            if not _service_up():
                ensure_service()
            args = {k: v for k, v in kwargs.items() if v is not None}
            r = httpx.post(f"{BASE}/call/{name}", json=args, headers={**HEADERS, "X-CC-Client": client_name}, timeout=320)
            return r.json()
        res = await asyncio.to_thread(_do)
        if not res.get("ok"):
            return [TextContent(type="text", text=json.dumps({"error": res.get("error", res)}, ensure_ascii=False))]
        return _content(res["result"])

    # Give the proxy a real signature so the SDK derives the same JSON schema the service publishes.
    params, annotations = [], {}
    for pname, p in props.items():
        t = _PY.get(p.get("type", "string"), str)
        if pname in required:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=t))
            annotations[pname] = t
        else:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=t | None, default=p.get("default")))
            annotations[pname] = t | None
    proxy.__signature__ = inspect.Signature(params)
    proxy.__annotations__ = annotations
    proxy.__name__ = name
    proxy.__doc__ = spec["description"]
    return proxy


def build_server(client_name: str) -> MCPServer:
    ensure_service()
    specs = httpx.get(BASE + "/tools", headers=HEADERS, timeout=5).json()
    server = MCPServer("computer-control", instructions=(
        "Local Windows desktop control. Loop: observe (get_screenshot / inspect_ui) -> act -> observe again -> verify. "
        "Prefer inspect_ui/find_ui_element + click_element over pixel clicks; use screenshots to confirm. "
        "Coordinates are virtual-desktop physical pixels; monitors can be at negative offsets (see list_monitors)."
    ), log_level="WARNING")
    for s in specs:
        server.add_tool(_make_proxy(s, client_name), name=s["name"], description=s["description"])
    return server


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=os.environ.get("CC_CLIENT", "mcp"))
    a = ap.parse_args()
    build_server(a.client).run("stdio")


if __name__ == "__main__":
    main()
