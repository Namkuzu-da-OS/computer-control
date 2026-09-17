"""Launcher for the voice front end, run by the REAL pythonw.exe (GUI subsystem, no console).

Why not .venv\Scripts\pythonw.exe: on uv venvs that file is a trampoline that spawns the base
python.exe, a console program, so a terminal window appears (and closing it kills the app).
This script makes the base pythonw.exe see the venv's packages instead.
"""
import os, runpy, site, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site.addsitedir(os.path.join(root, ".venv", "Lib", "site-packages"))
sys.path.insert(0, root)
os.chdir(root)
runpy.run_module("computer_control.voice.app", run_name="__main__")
