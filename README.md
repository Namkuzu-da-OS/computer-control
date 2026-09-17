# computer-control

Local, agent-agnostic desktop control for this Windows workstation. Built as an
accessibility layer: the goal is zero required mouse/keyboard use. Any agent
(Claude Code, Codex, a local LLM, a voice front end) drives the same engine.

```
Voice ──▶ Agent / LLM
              │  MCP (stdio)  |  REST (localhost)  |  future adapters
              ▼
   computer-control SERVICE  (FastAPI, 127.0.0.1:7710, token-auth, JSONL log)
              │
   ┌──────────┼──────────────┬──────────────┐
 UI Automation   SendInput     mss screenshots   Win32 windows   PowerShell
 (uiautomation)  mouse/keys    (per-monitor)     (ctypes)        (gated)
              ▼
        Windows desktop (4 monitors, negative coords OK)
```

## Layout

```
computer_control/
  core/monitors.py   DPI awareness, monitor enumeration, position words (left/right/above/below/primary)
  core/input.py      mouse + keyboard via SendInput (Unicode typing, hotkeys, clipboard paste)
  core/windows.py    list/find/focus/move/resize/min/max/close/launch, move_to_monitor
  core/screen.py     desktop / monitor / window / region screenshots + change detection
  core/uia.py        Windows UI Automation: inspect tree, find, click_element, set_text, toggle, select, expand
  core/safety.py     confirmation gate for destructive shell commands only
  core/log.py        JSONL activity log (typed text redacted)
  registry.py        THE tool table: name, description, JSON schema, function (45 tools)
  service/app.py     REST engine  (GET /health, GET /tools, POST /call/{tool}, POST /batch)
  adapters/mcp_server.py   MCP stdio proxy, tools generated from /tools at startup
scripts/             start/stop service, register with Claude Code / Codex, autostart task
config/config.json   host, port, token (auto-generated on first run)
logs/YYYY-MM-DD.jsonl
```

Rule: **tools are defined once, in `registry.py`.** Adapters never contain control logic.

## Run

```powershell
scripts\start-service.ps1          # detached, idempotent (adapters also auto-start it)
scripts\stop-service.ps1
scripts\install-autostart.ps1      # optional logon Scheduled Task
```

Health: `Invoke-RestMethod http://127.0.0.1:7710/health`

## Connect an agent

**Claude Code** (already registered, user scope): `scripts\register-claude.ps1`
**Codex CLI / app** (already registered in `~/.codex/config.toml`): `scripts\register-codex.ps1`
Both launch the identical command:
`.venv\Scripts\python.exe -m computer_control.adapters.mcp_server --client <name>`

**Any other agent / script** – talk REST directly:

```http
GET  /tools                      X-CC-Token: <config/config.json token>
POST /call/click                 {"x": 1408, "y": 1050}
POST /call/get_monitor_screenshot {"monitor": "above", "max_width": 1600}
POST /batch                      [{"tool":"focus_window","args":{"window":"G HUB"}}, {"tool":"inspect_ui","args":{}}]
```

Responses: `{"ok": true, "result": {...}}`. Screenshots return `image_base64`, `mime`,
`region` (desktop rect captured), `image_scale`, `active_window`, `timestamp`, `monitors`.
Map image pixel → desktop: `desktop_x = region.x + image_x / image_scale`.

For OpenAI function-calling or any JSON-schema tool format, `/tools` is the source:
each entry has `name`, `description`, `schema` (JSON Schema object), `returns_image`.

## The agent loop

```
OBSERVE   get_screenshot / get_monitor_screenshot / inspect_ui / find_ui_element
REASON    pick the highest-level interface: API > PowerShell > browser DOM > UIA > pixels
ACT       click_element / set_text / hotkey / focus_window / move_window_to_monitor / run_powershell ...
OBSERVE   screenshot or find again
VERIFY    wait_for_element / wait_for_screen_change / compare inspect results
RECOVER   wrong focus → focus_window; dialog → inspect_ui finds its buttons; stale id → find again;
          no UIA tree → visual click at screenshot-derived coords; app frozen → run_powershell Stop-Process
```

Never assume a click worked. `click_element` returns which method fired
(`InvokePattern`, `TogglePattern`, `mouse`, ...); confirm with a second observation.

## Coordinates and monitors

Canonical space = Windows virtual desktop, physical pixels, per-monitor-DPI aware.
This machine (2026-09-16):

| id | position | bounds |
|----|----------|--------|
| 1 | above | (0,-1440) 2560×1440 |
| 2 | left | (-1080,-449) 1080×1920 portrait |
| 3 | right | (2560,-449) 1080×1920 portrait |
| 4 | primary | (0,0) 2560×1440 |

Every tool taking `monitor` accepts an id or a word: primary, left, right, above/upper/top, below/lower.

## UI Automation notes (learned on real apps)

- Electron/CEF apps (Logi Options+, G HUB) switch accessibility on lazily; the first
  query returns a near-empty tree. `inspect_ui` retries once automatically; if a
  `find` returns nothing right after focus, call it again.
- G HUB's web DOM is 20+ levels deep – `max_depth` default is 40 for that reason.
- `click_element` with `InvokePattern` is accepted by some CEF buttons but ignored by
  others (G HUB onboarding "SKIP"). If nothing changed, re-issue with `method="mouse"`.
- Element ids (`e12`) are valid until the next inspect/find. Names also work directly:
  `click_element(element="NO, THANKS")`.
- Chromium only exposes real bounds once the window is visible and not minimized.

## Safety

Only `run_powershell` is gated, and only for patterns like format/diskpart/partition
changes/user deletion/recursive wipe of a drive or home/shutdown. A gated call
returns `confirmation_required` + token; re-run with `confirm=<token>` after the
user says yes out loud. Everything else runs without prompts.

Local-only: binds 127.0.0.1, token header required, no outbound calls. Screenshots
leave the machine only when the calling agent sends them to its own model.

## Logs

`logs/YYYY-MM-DD.jsonl` – one line per call: ts, client, tool, args (typed text
redacted to length), result summary (images as byte counts), error, duration ms.

## Milestone proof (2026-09-16)

"Find the open Logitech app and go into keyboard assignments":
find_window → focus_window (hidden tray window revealed) → inspect_ui →
click_element("NO, THANKS") [InvokePattern] → screenshot verify → onboarding SKIP
[Invoke ignored → mouse fallback] → toggle_checkbox(marketing, off) → verify toggled=false
→ click CONFIRM → screenshot: G HUB main screen with Devices/Games/Community/Profiles
tabs visible in the UIA tree. Zero physical input. See `_Changelog` entry for the
G710 detection status.

## House rule: hand focus back

The user dictates by voice into whatever window is in front. Every agent sequence
must end with `focus_window` on the agent's own chat/terminal window. Never leave
the operated app in the foreground.

## Voice front end (terminal-less) — `computer_control/voice/app.py`

**Hold G1, talk, release.** G1 on the G710+ sends F13 (Logitech Gaming Software, M1
profile). The app records while the key is held, transcribes on Atlas Whisper
(`192.168.10.52:8910`, model tiny.en), hands the text to a headless Claude Code session
(claude-agent-sdk, `bypassPermissions`, cwd = the BigPic drive so CLAUDE.md and memory
load, MCP = this project's adapter), and speaks each reply through Atlas PocketTTS
(`:8912`, voice kokoro). A small always-on-top bubble (bottom-right, primary monitor)
shows state: yellow listening, blue thinking, purple working a tool, green speaking.
Talk again mid-answer and the old answer is cut and dropped (latest question wins).

- Config `config/voice.json` (talk key, STT/TTS urls + models, voice, mic device, effort).
- Log `logs/voice.log` (what it heard, brain errors).
- `scripts/start-voice.ps1` restart now · `scripts/install-voice.ps1` logon task `ComputerControlVoice`.
- If the brain connection dies it reconnects itself and says so out loud.
- Whisper repeat-hallucinations ("Good. Good. Good.") are collapsed before reaching the brain.

### After a reboot

Everything comes back without a terminal:

| what | how |
|---|---|
| control service `:7710` | Scheduled Task `ComputerControlService` (at logon) — adapters also auto-start it |
| voice bubble + G1 | Scheduled Task `ComputerControlVoice` (at logon) |
| G-key mapping | Logitech Gaming Software autostarts with Windows; mappings live in its profile |

Worst case: open a terminal, run `scripts\start-service.ps1` and `scripts\start-voice.ps1`.

### Pedal layout (G710+, M1)

| key | does |
|---|---|
| G1 | Talk to Claude (F13 → voice app) |
| G6 | Wispr Flow dictation (held Ctrl + Left Win) |
| Enter | Enter |

"Summon Claude" (bring the terminal to front, `scripts/summon.py`) still exists as an LGS command, unbound.

### Not this repo

The Linux Jarvis / namkuzu-da-os project is a separate system for the Linux nodes.
This project is its Windows counterpart. They share only the Atlas speech endpoints.

### Latency and model (2026-09-16 evening)

- The voice brain runs **Sonnet 5** (`"model"` in `config/voice.json`); set it to `null` for the
  account default (Fable 5.1, more capable, slower per step). It speaks the `ack` ("On it.")
  immediately, and each turn logs `turn 9.5s: list_windows@0.0s say@6.5s ...` to `logs/voice.log`.
- Known issue, first Sonnet session: asked to "switch back to desktop 3" it called
  `close_window` twice instead of a Win+Ctrl+Arrow hotkey. A follow-up "desktop one" went
  through correctly in 3 s. If Sonnet keeps misreading desktop switches, either go back to
  Fable or add a deterministic "desktop N" shortcut in the app before the brain is consulted.
- Whisper stays on tiny.en, TTS on Pocket kokoro, by choice: fast enough and good enough.

### Pitfalls fixed 2026-09-16 (late evening) — read before touching `voice/app.py` or the task

Three bugs, all found by Daryll on the pedal, all fixed and verified the same evening.

1. **"You answer the previous question while doing the current one."** (`c75dff3`)
   The SDK exposes one ordered message stream per session. `Brain._ask` used to `break` out of
   `receive_response()` when G1 interrupted a turn, leaving that turn's remaining messages and
   its `ResultMessage` queued. The next question read the leftovers first (spoke the old answer)
   and stopped at the old result, so replies ran exactly one question behind while tool calls,
   executed inside the CLI, stayed current. **Rule: never abandon a turn mid-stream.** An
   interrupted turn now drains silently to its own `ResultMessage` (`(interrupted, drained K)`
   in the log), the next `query()` goes out only after that (15 s cap, else reconnect), and G1
   only interrupts when a turn is in flight. Fingerprint if it returns: `voice.log` turn lines
   with every mark at `@0.0s`. Repro that proved it: interrupt a 10-tool-call turn after 4 s,
   ask for PINEAPPLE, then BANANA; old code said nothing, then PINEAPPLE.
2. **A terminal window came with the app; closing it killed everything.** (`2c2fc3f`)
   `.venv\Scripts\pythonw.exe` is a uv trampoline that spawns the base console `python.exe`.
   The task now runs the base interpreter's real `pythonw.exe` with `scripts/voice-launch.py`
   (adds the venv site-packages). `install-voice.ps1` reads the base path from `pyvenv.cfg`.
3. **A Windows Terminal tab still appeared.** (`8bda335`)
   With a GUI parent, the Claude CLI child asked for a fresh console, and Windows Terminal
   (default terminal app) hosts it as a tab. `app.py` now patches `subprocess.Popen` to add
   `CREATE_NO_WINDOW`; MCP grandchildren inherit the hidden console.

Healthy state to check against (`Get-Process`): exactly one `pythonw.exe` whose command line is
`voice-launch.py`, its window title `tk`, child `claude.exe`, new `conhost` processes with
window handle 0, no new `OpenConsole`. Log ends with `brain connected`.

## keybridge — bare keys in, Wispr Flow combos out (2026-09-17)

`computer_control/keybridge/app.py`, logon task `ComputerControlKeybridge`, restart with `scripts\start-keybridge.ps1`,
config `config/keybridge.json`, log `logs/keybridge.log`.

Why it exists: Wispr Flow refuses any shortcut without a modifier (max 3 keys), the Belkin n52te can only send single
plain keys, and Wispr's default Ctrl+Win collided with desktop switching (Ctrl+Win+Arrow) — its own config showed the
"dictation cancelled by another shortcut" notice fired 80 times. So every device sends one plain key and the bridge
holds/taps the combo:

| physical key | sent by | bridge sends | Wispr binding |
|---|---|---|---|
| Home (hold) | keyboard, G710 **G4**, n52te key 04 | Ctrl+Alt+F9 held | push-to-talk |
| Insert (tap) | keyboard, G710 **G6**, n52te key 10 | Ctrl+Alt+F10 tapped | hands-free |
| F13 / Pause-Break | G710 G1 / n52te key 03 | — (voice app) | Talk to Claude |

Rules baked in: the bare key is swallowed (Home/Insert never reach an editor); a press with any
modifier already down passes through (Shift+Insert paste still works); injected events carry `dwExtraInfo=0xB19C` so
the bridge ignores its own output; modifiers are sent as LCtrl/LAlt because Wispr stores shortcuts as 162/164.
Wispr's Ctrl+Win entries were removed on 2026-09-17; LGS profile macros "Wispr Flow"/"Wispr Hands-free" were rewritten
in the profile XML (LCore stopped, `.bak-wispr-20260917` kept next to it, LCore restarted).
Verified: bridged hold and Insert tap each produced a Wispr history entry at 07:55 (first pass used Scroll Lock; replaced by Delete at 08:07, then Home at 08:12 (Daryll does use Delete), because Scroll Lock is a toggle key with an on-screen indicator on this machine — **never bind Caps Lock, Num Lock or Scroll Lock**, Daryll's rule).
