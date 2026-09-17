"""Launcher for the REST/MCP service, run by the REAL pythonw.exe (GUI subsystem, no console).

Same reason as voice-launch.py: on uv venvs, .venv\\Scripts\\pythonw.exe is a trampoline that spawns
the base python.exe -- a console program -- so a terminal window appears at logon and closing it kills
the service (it died that way on 2026-09-17, exit 0xC000013A, and only came back as a child of a
Claude Code session, which would have taken it down on exit). This script makes the base pythonw.exe
see the venv's packages instead.

Under pythonw there is no console, so sys.stdout/sys.stderr are None and uvicorn's logging setup dies
with exit 1 on the first write. Point them at logs/service.log before importing the app.
"""
import os, runpy, site, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site.addsitedir(os.path.join(root, ".venv", "Lib", "site-packages"))
sys.path.insert(0, root)
os.chdir(root)

os.makedirs(os.path.join(root, "logs"), exist_ok=True)
_log = open(os.path.join(root, "logs", "service.log"), "a", buffering=1, encoding="utf-8", errors="replace")
sys.stdout = sys.stderr = _log
sys.__stdout__ = sys.__stderr__ = _log  # uvicorn/click reach for the originals too

runpy.run_module("computer_control.service.app", run_name="__main__")
