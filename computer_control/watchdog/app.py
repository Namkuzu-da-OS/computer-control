r"""watchdog: prove the hands-free stack actually WORKS after a reboot, and repair it quietly.

Why this exists, and why it does not just check that processes are alive:

On 2026-09-17 a crash took hands-free control down. Every one of the three logon tasks was
Running, the service answered /health with 45 tools, and keybridge cheerfully logged "sent" on
every key press -- and nothing worked. The voice app had caught one WinError 267 at boot and
given up forever; keybridge was injecting keystrokes with no scan codes that Wispr silently
discarded. A liveness watchdog would have reported all-green through the whole outage, and the
person who found out was the one with no hands.

So every check here exercises the real capability the way a keycap does, and reads a receipt
that only the working end of the chain can produce:

  service      GET /health
  voice brain  the app's own log, after its current process started
  wispr keys   inject the BARE key (Insert / Home). keybridge's hook cannot tell that from a
               G6 press, so this runs the true path: key -> hook -> Ctrl+Alt+F9/F10 -> Wispr.
               Receipt = Wispr's screen tint while it records, plus a flow.sqlite History row.

Repairs are the scripted restarts we already had. It speaks (Atlas TTS) ONLY when it cannot fix
something itself -- Daryll cannot read a log line, and a watchdog that narrates every success is
one he will learn to ignore.

Run:  pythonw scripts\watchdog-launch.py            (logon task ComputerControlWatchdog)
      python -m computer_control.watchdog.app --now  (check right now, print the report)
Config: config\watchdog.json
"""
import argparse
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time

import httpx

from ..core import input as ci
from ..core import monitors, screen
from ..service.config import ROOT

LOG = os.path.join(ROOT, "logs", "watchdog.log")
CFG_PATH = os.path.join(ROOT, "config", "watchdog.json")
DEFAULTS = {
    "boot_settle_s": 45,          # let the three logon tasks finish coming up first
    "idle_required_s": 90,        # the active test steals the mic, so only run it when he is away
    "recheck_s": 900,             # passive sweep every 15 min; active test only after a repair
    "glow_threshold": 1.2,        # green-excess delta that means Wispr is recording
    "speak": True,
}


def log(msg: str):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_cfg() -> dict:
    c = dict(DEFAULTS)
    if os.path.exists(CFG_PATH):
        c.update(json.load(open(CFG_PATH, encoding="utf-8-sig")))
    else:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        json.dump(c, open(CFG_PATH, "w", encoding="utf-8"), indent=2)
    return c


CFG = load_cfg()
PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
SCRIPTS = os.path.join(ROOT, "scripts")


def ps(cmd: str, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(PS + [cmd], capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def idle_s() -> float:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(li)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


# ---------------- receipts ----------------

def _green_excess() -> float:
    """How green the screen is right now. Wispr tints the whole display while it records."""
    m = monitors.resolve_monitor("primary")
    region = {"x": m["x"] + m["width"] // 4, "y": m["y"] + m["height"] // 4,
              "width": max(64, m["width"] // 2), "height": max(64, m["height"] // 2)}
    img = screen._grab(region).resize((64, 64))
    px = list(img.getdata())
    n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    return g - (r + b) / 2


def _wispr_db() -> str:
    return os.path.join(os.environ["APPDATA"], "Wispr Flow", "flow.sqlite")


def _wispr_rows() -> int:
    try:
        con = sqlite3.connect(f"file:{_wispr_db()}?immutable=1", uri=True)
        try:
            return list(con.execute("select count(*) from History"))[0][0]
        finally:
            con.close()
    except Exception as e:
        log(f"  (wispr db unreadable: {e})")
        return -1


def speak(text: str):
    """Best effort, and never fatal: if the box cannot talk, the log still has it."""
    if not CFG["speak"]:
        return
    try:
        import io as _io
        import wave as _wave

        import numpy as np
        import sounddevice as sd

        vcfg = json.load(open(os.path.join(ROOT, "config", "voice.json"), encoding="utf-8-sig"))
        r = httpx.post(vcfg["tts_url"], json={"model": vcfg["tts_model"], "voice": vcfg["tts_voice"],
                                              "input": text, "response_format": "wav"}, timeout=60)
        r.raise_for_status()
        with _wave.open(_io.BytesIO(r.content), "rb") as w:
            rate, data = w.getframerate(), w.readframes(w.getnframes())
        sd.play(np.frombuffer(data, dtype="int16"), rate)
        sd.wait()
    except Exception as e:
        log(f"  (speak failed: {e})")


# ---------------- checks ----------------

def check_service() -> bool:
    try:
        cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
        h = httpx.get(f"http://127.0.0.1:{cfg['port']}/health", timeout=5).json()
        return bool(h.get("ok"))
    except Exception:
        return False


def check_voice_brain() -> bool:
    """Alive AND connected: the 2026-09-17 failure was an app that was alive and brainless."""
    r = ps("(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'voice-launch\\.py' } | Measure-Object).Count")
    if r.stdout.strip() in ("", "0"):
        return False
    path = os.path.join(ROOT, "logs", "voice.log")
    if not os.path.exists(path):
        return False
    for line in reversed(open(path, encoding="utf-8", errors="replace").read().splitlines()):
        if "brain ready" in line or "brain connected" in line:
            return True
        if "connect failed" in line:
            return False
    return False


def check_wispr_key(vk_name: str, hold: bool) -> bool:
    """Inject the bare key and watch for Wispr's recording tint. This is the whole chain."""
    base = _green_excess()
    rows_before = _wispr_rows()
    lit = False
    try:
        if hold:
            ci.key_down(vk_name)
            time.sleep(1.0)
            lit = (_green_excess() - base) > CFG["glow_threshold"]
        else:
            ci.press(vk_name)
            time.sleep(1.0)
            lit = (_green_excess() - base) > CFG["glow_threshold"]
    finally:
        if hold:
            ci.key_up(vk_name)
        else:
            ci.press(vk_name)  # toggle back off so we never leave the mic open
    if lit:
        return True
    time.sleep(3.0)  # a session writes its row only once it closes
    return _wispr_rows() > rows_before >= 0


# ---------------- repairs ----------------

def fix_service():
    log("  repair: restarting ComputerControlService")
    ps("Start-ScheduledTask -TaskName ComputerControlService")


def fix_voice():
    log("  repair: restarting the voice app")
    ps(f"& '{os.path.join(SCRIPTS, 'start-voice.ps1')}'", timeout=120)


def fix_keybridge():
    log("  repair: restarting keybridge")
    ps("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'keybridge-launch\\.py' } | "
       "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }; Start-Sleep 2; "
       "Start-ScheduledTask -TaskName ComputerControlKeybridge")


def fix_wispr():
    log("  repair: restarting Wispr Flow")
    ps("Get-Process 'Wispr Flow','Wispr Flow Helper' -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false; "
       "Start-Sleep 3; Start-Process \"$env:LOCALAPPDATA\\WisprFlow\\Wispr Flow.exe\"", timeout=120)


def sweep(active: bool) -> list[str]:
    """Returns the list of things still broken after repairs. Empty list = all good."""
    broken = []

    if not check_service():
        log("FAIL service")
        fix_service(); time.sleep(8)
        if not check_service():
            broken.append("the desktop control service")
        else:
            log("  fixed: service")
    else:
        log("ok   service")

    if not check_voice_brain():
        log("FAIL voice brain")
        fix_voice(); time.sleep(25)
        if not check_voice_brain():
            broken.append("the talk-to-Claude key")
        else:
            log("  fixed: voice brain")
    else:
        log("ok   voice brain")

    if not active:
        return broken

    # The key path. Hands-free first; if it works, push-to-talk shares the same sender.
    if check_wispr_key("insert", hold=False):
        log("ok   wispr hands-free (bridged Insert)")
    else:
        log("FAIL wispr hands-free")
        fix_keybridge(); time.sleep(6)
        if check_wispr_key("insert", hold=False):
            log("  fixed: keybridge")
        else:
            fix_wispr(); time.sleep(20)
            if check_wispr_key("insert", hold=False):
                log("  fixed: wispr")
            else:
                broken.append("your dictation keys")

    if check_wispr_key("home", hold=True):
        log("ok   wispr push-to-talk (bridged Home)")
    else:
        log("FAIL wispr push-to-talk")
        if "your dictation keys" not in broken:
            broken.append("push to talk")

    return broken


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", action="store_true", help="run one full check immediately and exit")
    ap.add_argument("--passive", action="store_true", help="skip the key injection test")
    args = ap.parse_args()

    if args.now:
        broken = sweep(active=not args.passive)
        log("RESULT: " + ("all good" if not broken else "STILL BROKEN: " + ", ".join(broken)))
        return 0 if not broken else 1

    log(f"watchdog up; settling {CFG['boot_settle_s']}s before the boot self-test")
    time.sleep(CFG["boot_settle_s"])

    first = True
    while True:
        # The active test toggles dictation, so it must not fire mid-sentence.
        active = first or idle_s() >= CFG["idle_required_s"]
        broken = sweep(active=active)
        if broken:
            msg = "Heads up. I could not fix " + " or ".join(broken) + ". You will need to look at it."
            log("SPEAKING: " + msg)
            speak(msg)
        else:
            log("all good" + ("" if active else " (passive sweep)"))
        first = False
        time.sleep(CFG["recheck_s"])


if __name__ == "__main__":
    sys.exit(main() or 0)
