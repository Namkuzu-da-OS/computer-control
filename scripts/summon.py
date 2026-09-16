"""One-shot summon: bring the Claude Code terminal to the front, or launch one.
Bound to the G710+ G1 key via Logitech Gaming Software (Shortcut command):
    <project>\\.venv\\Scripts\\pythonw.exe  <project>\\scripts\\summon.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WINDOW = "WindowsTerminal"
LAUNCH = 'wt.exe -d "G:\\Shared drives\\BigPic" claude'

try:
    import httpx
    from computer_control.service.config import load_config, base_url
    cfg = load_config()
    r = httpx.post(f"{base_url(cfg)}/call/focus_window", json={"window": WINDOW},
                   headers={"X-CC-Token": cfg["token"], "X-CC-Client": "summon-g1"}, timeout=5).json()
    if r.get("ok"):
        sys.exit(0)
except Exception:
    pass
subprocess.Popen(LAUNCH, shell=True)
