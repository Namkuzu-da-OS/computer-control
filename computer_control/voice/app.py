"""Terminal-less voice front end for this Windows PC.

Hold the talk key (F13, sent by the G710 G1 key via Logitech Gaming Software) ->
mic records -> Atlas Whisper transcribes -> a headless Claude Code session with the
computer-control tools acts -> the reply is spoken through Atlas TTS. A small
always-on-top bubble shows state and the last exchange. No terminal.

Run:  pythonw -m computer_control.voice.app     (scripts/install-voice.ps1 adds a logon task)
Config: config/voice.json (created with defaults on first run).
"""
import asyncio
import ctypes
from ctypes import wintypes
import io
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import wave

import httpx
import numpy as np
import sounddevice as sd

from ..service.config import ROOT

# This app runs under pythonw (no console). Any console child (the claude CLI, MCP servers) would otherwise
# get a brand-new visible console, which Windows opens as a Windows Terminal tab; closing that tab killed the
# whole app (2026-09-16). Force CREATE_NO_WINDOW on every subprocess; grandchildren inherit the hidden console.
if os.name == "nt":
    import subprocess

    _popen_init = subprocess.Popen.__init__

    def _popen_init_hidden(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _popen_init(self, *a, **kw)

    subprocess.Popen.__init__ = _popen_init_hidden

CFG_PATH = os.path.join(ROOT, "config", "voice.json")
DEFAULTS = {
    "talk_vk": [0x7C, 0x13],  # hold-to-talk keys: F13 = G710 G1 (LGS), Pause/Break = Belkin n52te key 03 (its 2008 editor has no F13)
    "stt_url": "http://192.168.10.52:8910/v1/audio/transcriptions",
    "stt_model": "Systran/faster-whisper-tiny.en",  # large-v3-turbo returns 500 on Atlas today (2026-09-16)
    "tts_url": "http://192.168.10.52:8912/v1/audio/speech",
    "tts_model": "pocket-tts",
    "tts_voice": "kokoro",
    "sample_rate": 16000,
    "input_device": None,
    "cwd": "G:\\Shared drives\\BigPic",
    "model": "claude-sonnet-5",  # voice needs snappy round trips; set null for the account default (Fable)
    "effort": "low",
    "ack": "On it.",  # spoken immediately after transcription; "" to disable
    "max_turns": 40,
    "bubble_monitor": "primary",
}


def load_cfg() -> dict:
    c = dict(DEFAULTS)
    if os.path.exists(CFG_PATH):
        saved = json.load(open(CFG_PATH, encoding="utf-8-sig"))
        c.update(saved)
        if set(DEFAULTS) - set(saved):  # new keys since the file was written: persist them with defaults
            json.dump(c, open(CFG_PATH, "w", encoding="utf-8"), indent=2)
    else:
        json.dump(DEFAULTS, open(CFG_PATH, "w", encoding="utf-8"), indent=2)
    return c


CFG = load_cfg()
LOG = os.path.join(ROOT, "logs", "voice.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)


def log(msg: str):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


# ---------------- audio ----------------

class Recorder:
    def __init__(self):
        self.frames: list[np.ndarray] = []
        self.stream = None

    def start(self):
        self.frames = []
        self.stream = sd.InputStream(samplerate=CFG["sample_rate"], channels=1, dtype="int16",
                                     device=CFG["input_device"], callback=lambda d, *_: self.frames.append(d.copy()))
        self.stream.start()

    def stop(self) -> bytes:
        if self.stream:
            self.stream.stop(); self.stream.close(); self.stream = None
        audio = np.concatenate(self.frames) if self.frames else np.zeros((0, 1), dtype="int16")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(CFG["sample_rate"]); w.writeframes(audio.tobytes())
        return buf.getvalue()


def transcribe(wav: bytes) -> str:
    r = httpx.post(CFG["stt_url"], files={"file": ("speech.wav", wav, "audio/wav")},
                   data={"model": CFG["stt_model"], "language": "en"}, timeout=60)
    r.raise_for_status()
    text = r.json().get("text", "").strip()
    # Whisper hallucinates on silence/noise ("Good. Good. Good. ..."); collapse any word repeated 3+ times in a row.
    text = re.sub(r"\b(\w+)([.,!?]?\s+\1\b[.,!?]?){2,}", r"\1", text, flags=re.I)
    return text.strip()


_speak_lock = threading.Lock()


def speak(text: str, stop_event: threading.Event):
    text = re.sub(r"[*_`#>]+", "", text).strip()
    if not text:
        return
    try:
        r = httpx.post(CFG["tts_url"], json={"model": CFG["tts_model"], "voice": CFG["tts_voice"], "input": text, "response_format": "wav"}, timeout=60)
        r.raise_for_status()
    except Exception as e:
        log(f"tts error: {e}"); return
    with wave.open(io.BytesIO(r.content), "rb") as w:
        rate, data = w.getframerate(), w.readframes(w.getnframes())
    pcm = np.frombuffer(data, dtype="int16")
    with _speak_lock:
        if stop_event.is_set():
            return
        sd.play(pcm, rate)
        while sd.get_stream().active:
            if stop_event.is_set():
                sd.stop(); break
            time.sleep(0.05)


# ---------------- talk key (low-level keyboard hook) ----------------

WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 13, 0x0100, 0x0101, 0x0104, 0x0105
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32 = ctypes.windll.user32
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowsHookExW.restype = wintypes.HHOOK


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def key_hook_thread(on_down, on_up):
    down = {"v": False}
    tv = CFG["talk_vk"]
    talk_keys = set(tv if isinstance(tv, list) else [tv])

    def proc(n, wparam, lparam):
        if n >= 0:
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if k.vkCode in talk_keys:
                if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN) and not down["v"]:
                    down["v"] = True; on_down()
                elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                    down["v"] = False; on_up()
                return 1  # swallow the talk key
        return user32.CallNextHookEx(None, n, wparam, lparam)

    cb = HOOKPROC(proc)
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, None, 0)
    if not hook:
        log("hook failed"); return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))


# ---------------- brain (headless Claude Code) ----------------

VOICE_RULES = (
    "You are being driven by voice on Daryll's Windows PC through a small bubble, not a terminal. "
    "Reply in one to three short spoken sentences; no markdown, no lists, no code. "
    "Use the computer-control tools to look at and operate the desktop. Speed matters more than certainty here: "
    "for simple one-step requests (a hotkey, switching desktops, focusing a window, pressing a button you can see) act in one call and answer; "
    "skip the verification screenshot unless the result is genuinely uncertain or he asked you to check. "
    "When you take a screenshot use max_width 1000 or less. "
    "Never tell him to click or type something himself. Do not bring a terminal to the front on your own initiative, but when he asks you to focus, click, or type into a terminal, do exactly that; his instruction always wins over this guidance. "
    "If a request needs a destructive step, ask one short yes or no question first."
)


class Brain:
    def __init__(self, ui):
        self.ui = ui
        self.loop = asyncio.new_event_loop()
        self.client = None
        self.task = None
        self.gen = 0
        self.stop_event = threading.Event()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._connect(), self.loop).result()

    async def _connect(self):
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
        opts = ClaudeAgentOptions(
            cwd=CFG["cwd"],
            permission_mode="bypassPermissions",
            system_prompt={"type": "preset", "preset": "claude_code", "append": VOICE_RULES},
            setting_sources=["user", "project"],
            mcp_servers={"computer-control": {"type": "stdio", "command": py, "args": ["-m", "computer_control.adapters.mcp_server", "--client", "voice"]}},
            model=CFG["model"], effort=CFG["effort"], max_turns=CFG["max_turns"],
            include_partial_messages=False,
            max_buffer_size=64 * 1024 * 1024,  # screenshots come back inline; the 1 MB default killed the session
        )
        self.client = ClaudeSDKClient(options=opts)
        await self.client.connect()
        self.task = None
        log("brain connected")

    async def _reconnect(self):
        try:
            await self.client.disconnect()
        except Exception:
            pass
        await self._connect()

    def ask(self, text: str):
        """Latest question wins: anything still in flight is interrupted and dropped."""
        self.gen += 1
        asyncio.run_coroutine_threadsafe(self._ask(text, self.gen), self.loop)

    def interrupt(self):
        self.stop_event.set()
        try:
            asyncio.run_coroutine_threadsafe(self.client.interrupt(), self.loop)
        except Exception:
            pass

    async def _ask(self, text: str, gen: int):
        from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, ResultMessage
        if self.task and not self.task.done():
            # Interrupt the in-flight turn and let its reader DRAIN to its ResultMessage. The SDK exposes one
            # ordered stream per session: if we abandon a turn mid-stream, its leftover messages (and its result
            # marker) are read by the next turn, which then speaks the previous answer and stops one result early.
            # That was the "one step behind" bug (2026-09-16).
            self.stop_event.set()
            try:
                await self.client.interrupt()
            except Exception:
                pass
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 15)
            except Exception:
                log("drain timed out; reconnecting for a clean stream")
                await self._reconnect()
        if gen != self.gen:
            return  # a newer question arrived while we waited
        self.stop_event.clear()
        self.task = asyncio.current_task()
        t0 = time.time()
        marks = []
        try:
            if CFG.get("ack"):
                asyncio.get_running_loop().run_in_executor(None, speak, CFG["ack"], self.stop_event)
            await self.client.query(text)
            spoken = []
            stale = 0
            async for m in self.client.receive_response():
                live = not self.stop_event.is_set() and gen == self.gen
                if not live:
                    stale += 1  # keep consuming silently until this turn's ResultMessage
                if isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            name = b.name.replace("mcp__computer-control__", "")
                            marks.append(f"{name}@{time.time() - t0:.1f}s")
                            if live:
                                self.ui.set_state("working", name)
                        elif isinstance(b, TextBlock) and b.text.strip() and live:
                            marks.append(f"say@{time.time() - t0:.1f}s")
                            spoken.append(b.text)
                            self.ui.set_state("speaking", b.text)
                            await asyncio.to_thread(speak, b.text, self.stop_event)
                elif isinstance(m, ResultMessage):
                    if live and not spoken and getattr(m, "result", None):
                        self.ui.set_state("speaking", m.result)
                        await asyncio.to_thread(speak, m.result, self.stop_event)
            log(f"turn {time.time() - t0:.1f}s{' (interrupted, drained %d)' % stale if stale else ''}: " + " ".join(marks))
            if gen == self.gen:
                self.ui.set_state("idle", "")
        except Exception as e:
            log(f"brain error: {e}")
            if gen != self.gen:
                return  # superseded turn: the newer turn owns the stream and any reconnect
            self.ui.set_state("thinking", "reconnecting...")
            try:
                await self._reconnect()
                self.ui.set_state("idle", "reconnected, ask again")
                await asyncio.to_thread(speak, "I lost my train of thought and reconnected. Ask me again.", threading.Event())
            except Exception as e2:
                log(f"reconnect failed: {e2}")
                self.ui.set_state("idle", f"error: {e2}")


# ---------------- bubble UI ----------------

COLORS = {"idle": "#3a3f4b", "listening": "#e0af68", "thinking": "#7aa2f7", "working": "#bb9af7", "speaking": "#9ece6a"}


class Bubble:
    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1a1b26")
        self.dot = tk.Canvas(self.root, width=18, height=18, bg="#1a1b26", highlightthickness=0)
        self.dot.grid(row=0, column=0, padx=(10, 6), pady=8)
        self.circle = self.dot.create_oval(2, 2, 16, 16, fill=COLORS["idle"], outline="")
        self.label = tk.Label(self.root, text="hold G1 and talk", fg="#c0caf5", bg="#1a1b26", font=("Segoe UI", 10), wraplength=420, justify="left", anchor="w")
        self.label.grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")
        self.root.bind("<ButtonPress-1>", self._drag_start); self.root.bind("<B1-Motion>", self._drag)
        self.root.after(80, self._pump)
        self._place()

    def _place(self):
        from ..core import monitors
        m = monitors.resolve_monitor(CFG["bubble_monitor"])
        wa = m["work_area"]
        self.root.update_idletasks()
        w, h = 470, self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{h}+{wa['x'] + wa['width'] - w - 16}+{wa['y'] + wa['height'] - h - 16}")

    def _drag_start(self, e): self._dx, self._dy = e.x, e.y
    def _drag(self, e): self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def set_state(self, state: str, text: str):
        self.q.put((state, text))

    def _pump(self):
        try:
            while True:
                state, text = self.q.get_nowait()
                self.dot.itemconfig(self.circle, fill=COLORS.get(state, COLORS["idle"]))
                self.label.config(text=(text or {"idle": "hold G1 and talk", "listening": "listening...", "thinking": "thinking..."}.get(state, state))[:400])
                self.root.update_idletasks(); self._place()
        except queue.Empty:
            pass
        self.root.after(80, self._pump)


# ---------------- main ----------------

def main():
    ui = Bubble()
    rec = Recorder()
    brain = {"b": None}
    state = {"recording": False}

    def boot():
        ui.set_state("thinking", "connecting to Claude...")
        try:
            brain["b"] = Brain(ui)
            ui.set_state("idle", "")
        except Exception as e:
            log(f"connect failed: {e}"); ui.set_state("idle", f"connect failed: {e}")
    threading.Thread(target=boot, daemon=True).start()

    def on_down():
        if brain["b"] is None:
            return
        if brain["b"].task and not brain["b"].task.done():
            brain["b"].interrupt()  # stop talking now; _ask drains the old turn before the new question is sent
        state["recording"] = True
        ui.set_state("listening", "")
        try:
            rec.start()
        except Exception as e:
            log(f"mic error: {e}"); ui.set_state("idle", f"mic error: {e}"); state["recording"] = False

    def on_up():
        if not state["recording"]:
            return
        state["recording"] = False
        wav = rec.stop()

        def work():
            ui.set_state("thinking", "transcribing...")
            try:
                text = transcribe(wav)
            except Exception as e:
                log(f"stt error: {e}"); ui.set_state("idle", f"hearing failed: {e}"); return
            if len(text) < 2:
                ui.set_state("idle", "(heard nothing)"); return
            log(f"heard: {text}")
            ui.set_state("thinking", f"you: {text}")
            brain["b"].ask(text)
        threading.Thread(target=work, daemon=True).start()

    threading.Thread(target=key_hook_thread, args=(on_down, on_up), daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
