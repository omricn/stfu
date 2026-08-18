# S.TFU — Noise Monitor & Nudge App

**Date:** 2026-08-17
**Status:** Approved design, ready for implementation planning
**Target:** Windows 11, single `.exe`, runs on a shared PC

---

## 1. Purpose

A tray-resident Windows app that listens to a gaming headset microphone and reacts when the user yells. The problem it solves is specific: long quiet stretches punctuated by sudden short shouts that wake the rest of the house. Detection is therefore tuned for **short spikes**, not sustained loudness.

The app is intentionally visible to the person it monitors — a tray icon, an obvious on-screen reaction, and a PIN gate rather than a hidden watchdog. It is a feedback device, not surveillance.

### Success criteria

1. A short yell (well under a second) reliably triggers a reaction.
2. Normal conversation, game audio, and mechanical noise (keyboard, mouse, chair) do not trigger it.
3. The operator can look at a report and answer "how many times last night, and when."
4. The app survives reboots, headset unplugging, and casual attempts to close it.

---

## 2. Behaviour specification

### 2.1 Detection

Two independent triggers. Either firing produces a trigger event.

| Trigger | Rule | Default |
|---|---|---|
| **Spike** | RMS over a rolling **150 ms** window exceeds the spike threshold | **Enabled** — primary |
| **Sustain** | RMS over a rolling **3 s** window exceeds the (lower) sustain threshold | **Disabled** |

The two rules share one cooldown, so a spurious trigger from either swallows the next genuine one. That makes the relationship between their thresholds load-bearing: **in adaptive mode the sustain threshold shifts with the spike threshold**, preserving the configured gap between them. Holding sustain fixed while spike adapts breaks badly — the adaptive floor (−20 dBFS) sits above the sustain default (−24 dBFS), so sustain would be permanently more sensitive than spike could ever be, firing on room noise once per cooldown period and starving the rule that actually matters.

150 ms is chosen deliberately: long enough to reject transients (keyboard slam, mouse click, desk knock, pop on the mic), short enough to catch a shout that lasts a fraction of a second.

### 2.2 Threshold modes

All three ship; one is active at a time, selected in Settings.

**Mode A — Calibration wizard (default)**
Three guided samples:
1. Silence, 10 s → noise floor
2. Normal talking, 10 s → speech ceiling
3. One yell → yell peak

Threshold is placed between the speech ceiling and the yell peak, biased toward the yell:

```
spike_threshold = speech_p95 + 0.6 * (yell_peak - speech_p95)
```

Rationale: false positives on ordinary conversation are far more corrosive to the app's credibility than a missed yell. The bias errs toward silence.

Sustain threshold, when enabled, is derived as `speech_p95 + 0.2 * (yell_peak - speech_p95)`.

Re-runnable at any time from the tray menu.

**Mode B — Manual / live meter**
A window with a real-time level bar and a draggable threshold line. Doubles as the diagnostic view when detection misbehaves — the operator can watch actual levels during normal use.

**Mode C — Adaptive**
Threshold tracks a rolling room baseline: `threshold = baseline + delta_db` (default `delta_db = 18`).

Three mandatory guards, without which this mode defeats itself in one direction or the other:
- **Exclusion** — frames already **at or above** the current threshold never enter the baseline, so a sustained loud stretch cannot drag the baseline upward.
- **Ceiling** (`adaptive_max_threshold_dbfs`, default −6 dBFS) — caps how high the computed threshold may go.
- **Floor** (`adaptive_min_threshold_dbfs`, default −20 dBFS) — caps how *low* it may go. In a silent room the baseline sits near −90 dBFS, and `baseline + 18` would put the threshold around −72 dBFS, where ordinary speech would trip it constantly.

Baseline is the median of the last 10 minutes of retained (non-excluded) frames.

Exclusion compares each frame against the **raw** `baseline + delta`, not against the floor-and-ceiling-clamped value, and the first frame always seeds the window. Comparing against the clamped value deadlocks: with an empty baseline the threshold reads as the floor, so in any room louder than the floor no frame is ever admitted and the threshold stays pinned there permanently.

**Consequence, by design:** the baseline ratchets **downward only**. It follows a room that gets quieter, but not one that gets louder — those are precisely the frames the exclusion guard rejects. This is the guard working, not a defect; the hazard being defended against is the threshold drifting upward until nothing triggers. A room that has genuinely become louder for good is handled by re-running calibration or switching modes, not by letting the threshold climb.

### 2.3 Cooldown

After any trigger fires, **30 s** of grace during which no further trigger events are produced. Configurable (`cooldown_seconds`, range 5–300).

Rationale for 30 s over a longer window: every loud noise should carry a consequence, but one continuous yell must not chain into multiple hits.

### 2.4 Strike ladder

Strike count is **session-cumulative**. There is no decay within a session.

| Event | Action |
|---|---|
| **First trigger of the session** | Minimize the foreground window, then show the **4-click overlay** |
| **Every subsequent trigger, all session** | **Win+D** to desktop + fullscreen message, 10 s auto-dismiss |

Once the ladder reaches the second rung it stays there. The Win+D action repeats indefinitely for the rest of the session — trigger 3, 4, 5 and 20 all produce the same response.

**Session definition** is configurable (`session_reset_mode`):

| Value | Session ends when |
|---|---|
| `session` *(default)* | App exits, user logs off, or PC sleeps |
| `rolling_60m` | 60 minutes elapse with no triggers |
| `nightly` | A fixed wall-clock time passes (default 04:00) |

### 2.5 Actions

**Always minimize first.** Before any visual action, the app minimizes the foreground window. This is a deliberate accepted trade-off: exclusive-fullscreen DirectX games will not reliably render another window on top, so the only way to guarantee the message is seen is to leave the game first. The consequence — that the first strike is as disruptive as the second — is accepted.

**Action 1 — 4-click overlay**
- Near-fullscreen window (~90% of the primary display), always-on-top, focus-forced
- Large message text
- A close (`X`) button that must be clicked **4 times**
- After each click the button **jumps to a new random position** within the overlay
- A visible counter ("3 more…") so the behaviour reads as intentional rather than broken
- No other dismissal path (Esc and Alt+F4 are suppressed)

**Action 2 — Desktop drop**
- Send `Win+D`
- Show a fullscreen message window for **10 s**, then auto-dismiss
- The game is left running underneath, untouched

**Action 3 — Sound bite**

A randomly chosen audio clip plays alongside every action, and if the operator has supplied pictures, a randomly chosen one appears in the popup **below** the text.

**The app ships with default sound effects** -- copied into the user's data folder during first-run setup. No pictures ship; the images folder is created empty for the operator to fill. Nobody should have to go and find sound effects before the app will react at all. They are seeded once, at setup, rather than on every launch: re-seeding would resurrect files the operator deleted on purpose. Everything remains replaceable.

**Clip library** lives at `%LOCALAPPDATA%\STFU\sounds\`:

```
sounds\
  first\      ← played on the first trigger of a session (overlay)
  repeat\     ← played on every subsequent trigger (desktop drop)
  *.wav|*.mp3|*.ogg|*.flac   ← loose files here are the shared fallback
```

Selection rules:
- Pick uniformly at random from the rung's folder.
- **Never play the same clip twice in a row** while the folder holds more than one file.
- If the rung folder is missing or empty, fall back to loose files in `sounds\`.
- If that is empty too, fall back to a built-in system beep, and log it once per session.

Behaviour:
- The folder is **rescanned on each trigger**, so dropping in new clips takes effect immediately — no restart, no settings change. (This is why the operator can add clips after the app is built and deployed.)
- Playback is asynchronous; the overlay appears without waiting for audio.
- A clip already playing is cut off by a new trigger rather than overlapping.
- Clips longer than `max_clip_seconds` (default 15 s) are truncated.
- `sound_gain` (default 1.0) scales playback level. System volume still applies — the app does not override it.
- Detection is **suppressed while a clip plays**, plus 200 ms after. Harmless with headphones, and it makes speaker setups safe by construction. Entering suppression also **clears the rolling detection windows**: they freeze rather than track audio while suppressed, and the spike window is full and loud at the instant a trigger fires, so without clearing them the first frame after the clip would land in a still-loud window and fire again on pre-clip audio.
- A **Test sound** button in Settings plays a random clip so the library can be verified without yelling at the PC.

**The shipped clips escalate too.** `first\` holds fart noises and a laugh -- embarrassing and funny. `repeat\` holds air horns -- jarring. The escalation is in the sound as well as the window.

**Pictures are optional and none ship with the app.** Drop your own into `%LOCALAPPDATA%\STFU\images\`; they are a single shared pool -- they are not rung-specific -- and follow the same rules: random, never the same one twice in a row, rescanned on every trigger. `.png` `.gif` `.jpg` `.jpeg`. Transparency is composited onto the window background rather than converted away, since a plain RGB conversion turns transparent pixels black and draws an ugly rectangle around the subject. An empty pictures folder simply means no picture.

Decoding uses `miniaudio` (WAV/MP3/OGG/FLAC in one small dependency); playback goes through `sounddevice` on the default output device. Unreadable or corrupt files are skipped and logged, never crash the trigger path.

### 2.6 First-run setup

**Every question the app needs is asked once, on the target machine, the first time it runs.** Nothing is pre-configured, and no setting has to be edited by hand. This matters practically — the person installing it may never have seen the machine before — and it is the only place the threshold can honestly be measured, since a yell's level depends on the headset, the room, and the person.

| Step | Question | Produces |
|---|---|---|
| 1. Welcome | none — explains what the app does, and that it is not hidden | — |
| 2. Microphone | which input device? (list, pick the one whose meter moves) | `device_name`, `device_hostapi` |
| 3. Calibrate | be quiet · talk normally · yell once | `spike_threshold_dbfs`, `sustain_threshold_dbfs` |
| 4. Test | try it, adjust and retry, or accept | confirmed threshold |
| 5. PIN | choose a PIN, entered twice | `pin_hash`, `pin_salt` |
| 6. Sound bites | opens the clip folders; add clips now or later | — |
| 7. Autostart | start with Windows? (default yes) | `autostart` |

The app counts as configured when `config.json` exists **and** both `device_name` and `pin_hash` are non-empty. Anything else re-runs the wizard — a half-finished setup is not a usable state.

Step 1 is not politeness. The design's whole stance is that this works as a feedback device the user knows about rather than a trap, and the first thing it does should say so.

### 2.7 Persistence and control

- **Autostart:** `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (no admin required)
- **Tray icon:** always visible; tooltip shows state (`Listening` / `Paused` / `No mic`)
- **Tray menu:** Report · Open sounds folder · Settings 🔒 · Calibrate 🔒 · Pause 15 min 🔒 · Exit 🔒
- **PIN:** gates Settings, Calibrate, Pause, and Exit. Stored as a PBKDF2-HMAC-SHA256 hash with a random per-install salt.

The PIN is an honest speed bump, not a security boundary. Anyone with admin rights can terminate any process; that is understood and acceptable for this use case.

### 2.8 Microphone handling

- The mic is **pinned** by **device name + host API name**, captured once during first-run setup. No device dropdown, no automatic switching to the default device. (PortAudio does not expose Windows device instance IDs; the name/host-API pair is the stable identifier available, and it survives reboots and replugs for a given headset.) If the host API changes but the name still matches, the pin still resolves — a driver-stack change should not orphan the setting.
- Capture is **WASAPI shared mode**, so Discord and in-game voice chat can use the same microphone concurrently.
- **Device disappears** (headset unplugged): monitoring pauses silently, tray icon greys out, a `mic_lost` event is logged. No nag, no alert.
- **Device returns:** monitoring resumes automatically, `mic_found` logged. The device is polled every 5 s while absent.

Setup assumption: **headset mic with headphones**. Game audio therefore never reaches the microphone, which is why a simple absolute threshold is viable.

---

## 3. Architecture

Single Python process, tray-resident, packaged with PyInstaller into one `.exe`.

### 3.1 Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `audio.py` | Open pinned device, emit 20 ms frames as dBFS. Handle unplug/replug and stream restart. | `sounddevice`, `numpy` |
| `detector.py` | Level stream → trigger events. Owns all three threshold modes and the cooldown gate. | *pure logic* |
| `strikes.py` | Session state machine. Maps a trigger event to an action name. | *pure logic* |
| `actions.py` | Named action registry and dispatcher. | `overlay`, `winapi` |
| `overlay.py` | The two Tk windows: 4-click overlay and 10 s fullscreen message. | `tkinter` |
| `sounds.py` | Clip library scan, random no-repeat selection, async playback. | `miniaudio`, `sounddevice` |
| `winapi.py` | Thin ctypes wrapper: minimize foreground window, send Win+D, force focus. | `ctypes` |
| `calibration.py` | Wizard flow and live-meter window. | `tkinter`, `audio` |
| `settings.py` | Config load/save/defaults, PIN hash + verify, autostart registry entry. | `json`, `winreg` |
| `logstore.py` | Append-only JSONL event log; query by date. | `json` |
| `report.py` | Report window: chart + table + CSV export. | `tkinter`, `matplotlib` |
| `tray.py` | Tray icon and menu, PIN prompts. | `pystray`, `Pillow` |
| `main.py` | Wiring, single-instance mutex, crash logging. | all |

`detector.py` and `strikes.py` have **no audio, UI, or Win32 dependencies**. They consume plain numbers and emit plain events. This is where correctness lives and where the tests concentrate.

### 3.2 Data flow

```
mic (pinned device)
  → 20 ms frames, 16 kHz mono
  → RMS → dBFS
  → detector: 150 ms peak window vs spike threshold
              (optional 3 s mean vs sustain threshold)
  → cooldown gate
  → strikes: first trigger of session, or later?
  → actions: minimize foreground
             → [4-click overlay] or [Win+D + 10 s message]
             → random sound bite from the clip library
  → logstore: append event
```

### 3.3 Units

All internal levels are **dBFS** (0 = full scale, negative below). The UI presents a normalized 0–100 meter so the operator never reads negative numbers. Conversion is a single documented function in `detector.py`; only the UI layer uses the 0–100 form.

### 3.4 Action plugin contract

```python
class Action:
    name: str
    def fire(self, event: TriggerEvent) -> None: ...
```

`actions.py` holds a name → instance registry. The strike ladder refers to actions **by name only**; config lists which names fire at which rung. Adding a new action means writing one class and adding its name to a list.

A **disabled `usb_light` stub** ships with the first version, with serial/HID call sites marked `TODO`, so a future USB indicator light is a fill-in-the-blank rather than a refactor.

### 3.5 Storage

`%LOCALAPPDATA%\STFU\`

| File | Contents |
|---|---|
| `config.json` | Settings, thresholds, PIN hash + salt, pinned device ID |
| `events.jsonl` | One JSON object per line, append-only |
| `app.log` | Rotating diagnostic log |
| `sounds\first\` | Operator-supplied clips for the first trigger of a session |
| `sounds\repeat\` | Operator-supplied clips for every later trigger |
| `sounds\` | Loose clips used as fallback when a rung folder is empty |

All three `sounds` folders are created empty on first run. A tray menu item **Open sounds folder** launches Explorer there, so adding clips is drag-and-drop.

**Event record:**

```json
{
  "ts": "2026-08-17T21:43:12.482+03:00",
  "session_id": "2026-08-17T19:02:11",
  "type": "trigger",
  "trigger": "spike",
  "level_dbfs": -8.3,
  "threshold_dbfs": -14.0,
  "strike_index": 3,
  "action": "desktop_drop",
  "sound": "repeat/airhorn.mp3"
}
```

`type` is one of `trigger`, `session_start`, `session_end`, `mic_lost`, `mic_found`, `app_paused`, `app_resumed`.

Every session gets its own `session_start`, including one begun by a `rolling_60m` or `nightly` rollover mid-run, and the outgoing session gets a `session_end` at the same moment. The report groups by `session_id`, so a session whose triggers exist but whose start was never written would appear in the log with no beginning.

A trigger is **written before its action is dispatched**, stamped with the time of the yell rather than the time of the write. Actions can block indefinitely — the 4-click overlay waits for the user — which would otherwise date every record to when the action finished and lose the record entirely if the process were killed while the overlay was open.

**Events only.** No continuous level history is stored.

---

## 4. Report window

Opens from the tray, no PIN required.

- **Date picker** — sessions present in the log
- **Chart** (matplotlib, embedded in Tk) — trigger events across the session's wall-clock span; one marker per event, marker height = peak level, colour = action fired
- **Table** (`ttk.Treeview`) — timestamp, peak dB, trigger type, strike index, action taken
- **Export CSV** button

Non-trigger events (`mic_lost`, `app_paused`) appear in the table as distinct rows so gaps in coverage are visible.

---

## 5. Error handling

| Condition | Behaviour |
|---|---|
| Pinned mic absent at startup | Start in `No mic` state, poll every 5 s, log `mic_lost` |
| Mic disappears while running | Pause, grey tray icon, log `mic_lost`, poll for return |
| Audio stream error | Restart the stream with exponential backoff (1 s → 30 s cap) |
| 3 consecutive stream failures | Tray notification; keep retrying |
| Overlay already displayed | Suppress the duplicate; still log the event |
| Second instance launched | Single-instance mutex; second instance exits and focuses the tray icon |
| Unhandled exception | Write to `app.log` with traceback; app keeps running |
| Corrupt `config.json` | Back up to `config.json.bad`, regenerate defaults, log it |

---

## 6. Testing strategy

### Unit tests (the bulk)

- dBFS conversion and RMS math against known waveforms
- Spike detection: synthetic 150 ms burst above threshold → fires; 30 ms transient → does not
- Sustain detection with synthetic level sequences
- Adaptive baseline: verify a long loud stretch does **not** raise the threshold (the guard), and that the ceiling holds
- Cooldown gate: triggers inside the window are suppressed, the first one after is not
- Strike state machine: first trigger → overlay; triggers 2..N → desktop drop; each reset mode ends the session correctly
- Wizard threshold computation from sample sets
- Config load/save round-trip, defaulting, and corrupt-file recovery
- PIN hash and verify
- Clip selection: never repeats consecutively with 2+ files; a single file repeats fine; empty rung falls back to loose clips, then to the beep; unsupported and corrupt files are skipped without raising

### Integration test

A fake audio source feeds a scripted level sequence into the real detector and strike manager, with a recording fake in place of the action registry. Asserts the exact action sequence and timing. No microphone, no windows, no Win32.

### Manual test checklist

Tk and Win32 behaviour is verified by hand and documented as a checklist:
minimize-then-overlay against a fullscreen game · 4-click X randomization · Win+D + 10 s auto-dismiss · tray menu and PIN gates · autostart after reboot · headset unplug/replug · report window rendering · clip playback for each supported format, and clips added while the app is running taking effect on the next trigger.

---

## 7. Packaging and deployment

- Built with **PyInstaller** (`--onefile --noconsole`) on the development machine
- Dependencies: `sounddevice`, `numpy`, `miniaudio`, `pystray`, `Pillow`, `matplotlib`
- Deployment is copying one `.exe` to the target PC and running it once; first run performs setup (PIN, mic pinning, calibration wizard) and registers autostart
- No Python installation required on the target machine

**Known packaging caveat:** freshly built PyInstaller executables are occasionally flagged heuristically by Windows Defender. Mitigation is an exclusion for the install folder or signing the binary. This is expected and not a defect.

---

## 8. Decisions and rationale

| Decision | Rationale |
|---|---|
| Spike detection over sustain | The actual problem is short shouts after long quiet, not continuous volume |
| 150 ms window | Rejects transients, catches sub-second yells |
| Threshold biased toward the yell | A false positive on normal speech destroys trust in the app faster than a missed yell |
| Always minimize before showing | Only reliable way to surface a window over an exclusive-fullscreen game |
| Session-cumulative strikes, no decay | Isolated yells spread across a night are the problem; a short reset window would never escalate |
| 30 s cooldown | Every loud noise carries a consequence; one continuous yell does not chain |
| Events-only logging | The chart is about *when and how often*, not waveform archaeology |
| Visible tray + PIN, not a hidden watchdog | The app works as a feedback device the user knows about; the log is the operator's evidence |
| Python + PyInstaller | Matches the available toolchain; audio and charting are far less code than in C# |
| Actions behind a name registry | A future USB indicator light is one new class, not a refactor |
| Sound clips supplied by the operator, folder rescanned per trigger | Clips get added after deployment; nothing ships with the app and no restart is needed to change the library |
| Separate `first\` and `repeat\` clip folders | The two rungs mean different things; the audio should be able to say so |
| Detection suppressed during clip playback | Prevents the app triggering on its own sound on any speaker-based setup |

## 9. Explicitly out of scope

- Speech recognition or content analysis — level only
- Remote monitoring, network reporting, or cloud sync
- Blocking input, locking the workstation, or killing the game
- Multi-user or multi-PC support
- USB light hardware integration (stub only in v1)
