"""Launcher for keybridge under the REAL pythonw.exe (no console). See voice-launch.py for why."""
import os, runpy, site, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site.addsitedir(os.path.join(root, ".venv", "Lib", "site-packages"))
sys.path.insert(0, root)
os.chdir(root)
runpy.run_module("computer_control.keybridge.app", run_name="__main__")
