# S.TFU

[![CI](https://github.com/omricn/stfu-public/actions/workflows/ci.yml/badge.svg)](https://github.com/omricn/stfu-public/actions/workflows/ci.yml)

A Windows tray app that listens to a microphone and interrupts you when you yell.

Built for a specific problem: someone gaming with headphones on, quiet for an hour, then suddenly shouting loud enough to wake the house. Detection is tuned for **short spikes**, not sustained volume — the thing that wakes people is the sudden one, not the steady one.

**It is deliberately not subtle, and deliberately not hidden.** It has a tray icon, it announces what it does on first run, and the person being monitored is meant to know it's there.

---

## What it actually does

| When | What happens |
|---|---|
| **First yell of a session** | Minimises whatever's in the foreground, plays a random sound effect, and shows a near-fullscreen overlay whose close button jumps to a new random spot after each of **four** clicks |
| **Every later yell that session** | `Win+D` to the desktop, a different sound, and a fullscreen message for 10 seconds |

There's a 30-second cooldown, so one long yell can't chain into several punishments. The escalation is session-cumulative and doesn't decay: once you've had the first one, every subsequent yell that evening goes straight to the desktop drop.

Every trigger is logged. A built-in report window shows a chart of when they happened, a table of the detail, and a CSV export.

### Why it minimises first

Exclusive-fullscreen games won't reliably let another window draw on top of them. The only way to guarantee the message is actually seen is to leave the game first. This makes the first strike as disruptive as the second — an accepted trade-off, not an oversight.

---

## Install

**Option A — download the exe.** Grab `stfu.exe` from [Releases](../../releases), copy it anywhere, run it.

Windows SmartScreen will warn you: the binary is **not code-signed**. Click *More info* → *Run anyway*.

The warning comes from the "mark of the web" tag Windows attaches to downloads, not from anything in the file. You can clear it:

```powershell
Unblock-File .\stfu.exe
```

A copy handed over on a USB stick or a network share never gets tagged in the first place. If none of that satisfies you — reasonably — use Option B and build it yourself.

**Option B — build it yourself.**

```bash
git clone https://github.com/omricn/stfu-public.git
cd stfu-public
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
powershell -File build.ps1
```

The exe lands in `dist/`. Requires Python 3.12 — 3.13+ may not have wheels for every dependency yet.

---

## First run

It asks everything it needs once, then never again:

1. **Welcome** — what it does, and that it isn't hidden
2. **Microphone** — pick the device you actually use; watch the meter move
3. **Calibrate** — be quiet for 10s, talk normally for 10s, then yell once
4. **Test** — try it
5. **PIN** — needed to change settings or close the app
6. **Sound effects** — opens the clips folder
7. **Autostart** — start with Windows (default yes)

**The calibration step is the whole ballgame.** A yell's level depends on your mic, your room, and your voice — there is no sensible universal number. It measures the gap between your speaking voice and your yell and places the threshold 60% of the way up, biased toward the yell, because a false positive on normal conversation destroys trust in the app far faster than an occasional missed shout.

You can re-run calibration any time from Settings.

---

## Sounds and pictures

Everything lives in `%LOCALAPPDATA%\STFU\`:

```
sounds\first\    plays on the first yell of a session
sounds\repeat\   plays on every later one
images\          optional pictures shown in the popups
```

`.wav` `.mp3` `.ogg` `.flac` for audio, `.png` `.gif` `.jpg` `.jpeg` for pictures.

**Drop files in while the app is running** — the folders are rescanned on every trigger, so new clips work immediately with no restart. The same clip never plays twice in a row.

The two folders are separate on purpose: put something embarrassing in `first\` and something jarring in `repeat\`, and the escalation is in the sound as well as the window.

**No pictures ship with the app.** The folder is created empty. Add your own and they appear in both popups, below the text. Leave it empty and you just get text.

Some sound effects are bundled to get you started — see [the licence](LICENSE), they are not covered by it and you should replace them before redistributing.

---

## Settings and the tray

Right-click the tray icon:

**Report** · **Open sounds folder** · **Settings** 🔒 · **Recalibrate** 🔒 · **Pause 15 min** 🔒 · **Exit** 🔒

🔒 items ask for the PIN. The icon is green when listening, amber when paused, grey when the microphone is missing.

Settings exposes **every** changeable setting — threshold mode and thresholds, detection window lengths, cooldown, session-reset behaviour, the adaptive-mode parameters, overlay clicks, message duration, sound volume and clip length, and autostart.

Two of them are worth knowing about:

- **Show popups** — off means it detects and logs but never interrupts
- **Play sounds** — off means silent reactions

Turn both off and you get a **log-only mode**. Worth running for a night after calibrating: you can check the threshold is catching the right things from the report, before it starts interrupting anyone.

### Threshold modes

- **Wizard** *(default)* — the fixed number calibration measured
- **Manual** — set it yourself against a live meter
- **Adaptive** — tracks the room's baseline and fires relative to it

Adaptive deliberately ratchets **downward only**: it follows a room that gets quieter, but not one that gets louder, because a threshold that drifts upward eventually stops firing at all. If the room has genuinely changed for good, re-run calibration.

---

## Privacy

**No audio is recorded, transmitted, or stored — ever.** The app computes a loudness number from each 20 ms frame and throws the samples away immediately. Nothing is written to disk except event records: a timestamp, a level in dBFS, and which action fired.

There is no network code in this project at all. Nothing leaves the machine.

---

## A note on installing this on someone else's computer

This app takes over the screen and monitors a microphone. Whoever is being monitored should know it's there and why — which is why the first screen says so plainly, the tray icon is always visible, and the PIN is described as a speed bump rather than a lock.

It works best as something agreed to. Used as a hidden trap, it will be found, resented, and uninstalled — and it isn't built to survive that anyway: anyone with admin rights can end any process.

---

## How it's built

```
stfu/
  levels.py      RMS, dBFS, display meter
  config.py      settings, validation, PIN hashing
  detector.py    spike + sustain rules, three threshold modes, cooldown
  strikes.py     the escalation ladder
  logstore.py    append-only JSONL event log
  audio.py       pinned-device capture (the only module touching hardware)
  engine.py      wires detection to actions and the log
  winapi.py      minimise / show-desktop
  sounds.py      clip library and playback
  images.py      picture library
  overlay.py     the two popup windows
  actions.py     named action registry
  uibridge.py    cross-thread UI marshalling
  ...            first-run wizard, tray, report, settings, packaging
```

`levels`, `config`, `detector`, `strikes`, `logstore` and `engine` are pure decision logic with **no audio, UI, or Win32 imports** — a test enforces that mechanically by inspecting their ASTs. That's why the detection logic is testable without a microphone, and it's most of why there are 279 tests.

See [docs/DESIGN.md](docs/DESIGN.md) for why the design is the way it is — the thresholds, the escalation rules, the failure modes, and the trade-offs that were accepted deliberately.

```bash
.venv/Scripts/python -m pytest
```

There is also a headless CLI for tuning without the GUI:

```bash
.venv/Scripts/python -m stfu.cli devices
.venv/Scripts/python -m stfu.cli pin "Microphone (Your Headset)" "Windows WASAPI"
.venv/Scripts/python -m stfu.cli monitor --meter
```

`monitor` prints what it *would* do; add `--real` to actually do it.

---

## Known limitations

- **Unsigned binary** — SmartScreen will warn. `Unblock-File` clears it, or build from source.
- **Exclusive-fullscreen games** — handled by minimising first, but behaviour varies by title. Worth testing with yours.
- **DPI scaling** — the overlay is laid out relative to screen size; heavily scaled displays are less tested.
- **Windows only** — `winreg`, Win32 minimise/show-desktop, and WASAPI capture are all Windows-specific.

## Uninstalling

Run `uninstall.bat` (shipped alongside the exe, and readable — it's a plain batch file, not a compiled installer). It stops the app, removes the start-with-Windows entry, and deletes `%LOCALAPPDATA%\STFU`, after copying your event log to the Desktop first.

Then delete `stfu.exe` yourself. That's everything — the app writes nothing anywhere else.

---

## Licence

MIT for the code. **The bundled sound effects are not covered** — see [LICENSE](LICENSE).
