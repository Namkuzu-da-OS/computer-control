"""The control engine as a local REST service (FastAPI, 127.0.0.1 only).

  GET  /health                 -> {ok, version, tools, uptime_s}
  GET  /tools                  -> tool specs (name, description, JSON schema, returns_image)
  POST /call/{tool}  {args}    -> {ok, result} | {ok:false, error}
  POST /batch  [{tool,args}]   -> list of results, stops at first error unless continue_on_error

Auth: header  X-CC-Token: <token from config/config.json>   (loopback-only, but the
token stops any random local webpage from driving the desktop via CSRF).
Client id: header X-CC-Client (free text, logged).
"""
import json
import os
import time
import traceback

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import registry, __version__
from ..core import log
from .config import load_config

CFG = load_config()
app = FastAPI(title="computer-control", version=__version__)
_t0 = time.time()


def _auth(token: str | None):
    if CFG.get("token") and token != CFG["token"]:
        raise HTTPException(401, "bad or missing X-CC-Token")


@app.get("/health")
def health():
    return {"ok": True, "version": __version__, "tools": len(registry.TOOLS), "uptime_s": round(time.time() - _t0, 1), "pid": os.getpid()}


@app.get("/tools")
def tools(x_cc_token: str | None = Header(default=None)):
    _auth(x_cc_token)
    return registry.specs()


def _run(tool: str, args: dict, client: str) -> dict:
    t0 = time.perf_counter()
    try:
        result = registry.call(tool, args)
        log.record(client, tool, args, result=result, ms=(time.perf_counter() - t0) * 1000)
        return {"ok": True, "tool": tool, "result": result}
    except KeyError as e:
        log.record(client, tool, args, error=str(e))
        raise HTTPException(404, str(e))
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        log.record(client, tool, args, error=err, ms=(time.perf_counter() - t0) * 1000)
        return {"ok": False, "tool": tool, "error": err, "trace": traceback.format_exc()[-1500:]}


@app.post("/call/{tool}")
async def call(tool: str, request: Request, x_cc_token: str | None = Header(default=None), x_cc_client: str | None = Header(default=None)):
    _auth(x_cc_token)
    body = await request.body()
    args = json.loads(body) if body else {}
    if not isinstance(args, dict):
        raise HTTPException(400, "body must be a JSON object of arguments")
    return JSONResponse(_run(tool, args, x_cc_client or "http"))


@app.post("/batch")
async def batch(request: Request, x_cc_token: str | None = Header(default=None), x_cc_client: str | None = Header(default=None)):
    _auth(x_cc_token)
    body = await request.json()
    steps = body if isinstance(body, list) else body.get("steps", [])
    cont = isinstance(body, dict) and body.get("continue_on_error", False)
    out = []
    for s in steps:
        r = _run(s["tool"], s.get("args", {}), x_cc_client or "http")
        out.append(r)
        if not r["ok"] and not cont:
            break
    return out


def main():
    import uvicorn
    uvicorn.run(app, host=CFG.get("host", "127.0.0.1"), port=int(CFG.get("port", 7710)), log_level="warning")


if __name__ == "__main__":
    main()
