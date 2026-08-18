# S.TFU brand and UI

**S.T.F.U — Sound Trigger Focus Utility.** *Silence is productivity.*

The mark is a waveform: rounded vertical bars, tallest at the centre, falling
away symmetrically. It reads as sound, and the fact that it is *still* reads as
silence. Everything else follows from it.

---

## Palette

Taken from the dark splash artwork, which is the fullest expression of the mark.

| Token | Hex | Use |
|---|---|---|
| `INK` | `#0d0d10` | Window background |
| `SURFACE` | `#16161b` | Cards, form rows, input wells |
| `SURFACE_HI` | `#1f1f26` | Hover, selected rows, the meter's track |
| `HAIRLINE` | `#2a2a33` | Borders, dividers, the faint concentric rings |
| `INDIGO` | `#6c63f5` | Primary accent — outer bars, the dots in S.T.F.U, focus rings |
| `AMBER` | `#f5a623` | Mid bars, warnings, the paused state |
| `RED` | `#ef4136` | Centre bar, the trigger itself, over-threshold, destructive actions |
| `TEXT` | `#f2f2f5` | Primary text |
| `TEXT_DIM` | `#8a8a95` | Secondary text, the tagline, help copy |
| `GREEN` | `#3ddc84` | Listening / healthy only — not part of the mark, but the tray needs it |

**The three accents are ordered, not interchangeable.** Indigo is calm and
outermost, amber is elevated, red is the peak. The same order carries the
meter: indigo below threshold, amber approaching it, red over it. A reader who
has seen the logo already knows what red means.

## Type

Segoe UI throughout — it is on every Windows machine and needs no bundling.

| Role | Size / weight |
|---|---|
| Screen title | 22 semibold |
| Section heading | 13 semibold, `TEXT_DIM`, letter-spaced |
| Body | 10 regular |
| Wordmark | 28 light, letter-spaced wide — `S . T . F . U` |
| Tagline | 8 regular, `TEXT_DIM`, letter-spaced wide |

The wordmark's wide letter-spacing is the logo's most recognisable typographic
trait. Keep it wherever the name is set as a mark rather than as running text.

## Shape and spacing

- Corner radius 8 on cards and buttons, 12 on the splash
- 16 px gutters, 12 px between form rows, 24 px above a section heading
- One accent per screen region. A form is grey until something needs attention.

---

## The splash

Shown **on every launch** — first run and every start after — then dismissed.

- Borderless, centred, ~480 × 420, `INK`, radius 12
- The waveform animates: bars rise and fall in a slow wave, centre-outward
- Below it the wordmark, the tagline, and a tri-colour progress bar filling
  indigo → amber → red
- Around 1.8 s, then it disappears into the app (or the wizard, on first run)

**The splash is light; the rest of the app is dark.** That is a deliberate,
owner-approved choice, not an oversight. The supplied `logo.gif` is the light
mark on white, and the splash takes its background from the gif's own first
frame rather than a hardcoded constant -- so a dark version dropped in at the
same path changes the splash with no code change. Do not "fix" the mismatch by
forcing the splash dark; that would put a dark window behind a white-background
animation.

**Source of the animation.** If `stfu/assets/brand/logo.gif` exists it is
played frame by frame. Otherwise the bars are drawn and animated in code from
the same geometry as the app icon. The fallback is not a placeholder — it is
resolution-independent, has no file to keep in sync, and can be driven by real
audio levels later, which a GIF cannot.

**It must never block startup.** The splash is decoration; monitoring is the
job. If it fails for any reason it is logged and skipped, exactly as the app
icon now is.

---

## Applying it to the existing screens

| Screen | Notes |
|---|---|
| First-run wizard | Dark, the mark at the top of every step, tri-colour step dots for progress |
| Settings | Grouped sections with headings, not one flat list of 20 rows |
| Live meter | The bar takes the accent order: indigo → amber → red as it crosses the threshold |
| Report | Dark chart, trigger markers in amber (popup) and red (desktop drop) |
| Calibration | The waveform reacts to the recording level — the mark doing its actual job |
| PIN | Small, centred, the mark above the field |
| Overlay / desktop message | Already dark. Add the mark, and set the message in the wordmark's style |

The overlay is the one screen that should **not** become tasteful. It exists to
be unwelcome. Brand it, but keep it loud.
