"""Launcher for the watchdog, run by the REAL pythonw.exe (GUI subsystem, no console).

Same trap as voice-launch.py / service-launch.py: the venv's pythonw.exe is a uv trampoline that
spawns a console python.exe. Under pythonw stdout/stderr are None, and this module prints, so
they are redirected before the module runs.
"""
import os, runpy, site, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site.addsitedir(os.path.join(root, ".venv", "Lib", "site-packages"))
sys.path.insert(0, root)
os.chdir(root)

os.makedirs(os.path.join(root, "logs"), exist_ok=True)
_log = open(os.path.join(root, "logs", "watchdog-stdout.log"), "a", buffering=1, encoding="utf-8", errors="replace")
sys.stdout = sys.stderr = _log
sys.__stdout__ = sys.__stderr__ = _log

runpy.run_module("computer_control.watchdog.app", run_name="__main__")
