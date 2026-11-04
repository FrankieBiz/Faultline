# FaultLine design system

FaultLine's pitch is evidence over claims, so the design is built from its own evidence. Both sites, the judge page (`docs/index.html`) and the local Inspector (`web/inspector-ui`), share this system.

## Concept: the seismogram of a repair

A seismograph records an event on a drum. The rupture is drawn in red, and the trace settles once it is over. FaultLine records a repair the same way: the checkout ruptures (HTTP 500), the model proposes a patch, independent checks run, and the record settles at 44/44. The signature visual is a helicorder trace of the recorded Meta job `3573b32b`, drawn at its real timing (0 to 13.039 s). The surface is soot, the trace is ink, and color appears only where something was observed.

Everything else stays quiet. One owned visual idea, real data and plain sentence-case type are what make it read as premium. Effects and template chrome are not.

## Color: soot, ink and three evidence hues

Color carries evidence only. Every hue is paired with a text or shape cue (a mark, a word or a position), never color alone.

| Token | Hex | Use |
| --- | --- | --- |
| `--soot` | `#0b0b0a` | Page background (the smoked drum) |
| `--drum` | `#141412` | Raised panels, the instrument face |
| `--well` | `#070706` | Inset wells: code, inputs, trace bed |
| `--ink` | `#eceef1` | Primary text, the trace, focus rings and pressed rims (test-pinned as rgb(236, 238, 241)) |
| `--ink-2` | `#a9abaf` | Secondary text (about 8.6:1 on soot) |
| `--ink-3` | `#8b8e93` | Tertiary text and axis labels (about 6:1 on soot) |
| `--hair` | `rgba(236,238,241,.10)` | Hairlines and grid |
| `--hair-strong` | `rgba(236,238,241,.18)` | Panel borders |
| `--control` | `rgba(236,238,241,.38)` | Control borders (3:1 or better on every surface, WCAG 1.4.11) |
| `--rupture` | `#ff5a4e` | Observed failure: HTTP 500, a failed check, a blocked deploy |
| `--verified` | `#6fdc97` | Observed pass: 44/44, a verified repair, an accepted patch |
| `--held` | `#f0b43c` | Not run, inconclusive, or let through by a naive check |

Cyan is retired. Show work in flight with ink plus motion. There are no glows, washes, gradients or colored edge stripes. A 6 to 8 percent tint of an evidence hue is allowed only behind the one element that carries that state.

## Typography

Self-hosted OFL faces with sha256-pinned files (see `docs/assets/fonts/`, mirrored in `web/inspector-ui/src/app/fonts/`):

- **Zalando Sans** (variable: width 75 to 125 percent, weight 200 to 900). Display, headings, text and labels.
- **Martian Mono** (variable: width 75 to 112.5 percent, weight 100 to 800). Only for code, diffs, commands, ids, timestamps, durations and readouts.

| Role | Size | Weight | Width | Notes |
| --- | --- | --- | --- | --- |
| Display (h1) | `clamp(3rem, 1.6rem + 5.6vw, 7rem)` | 780 | 76% | line-height .92, letter-spacing -.02em, `text-wrap: balance` |
| Heading 2 | `clamp(2rem, 1.4rem + 2.4vw, 3.5rem)` | 700 | 82% | line-height .98, letter-spacing -.015em |
| Heading 3 | `1.25rem` | 640 | 100% | line-height 1.25 |
| Lede | `1.1875rem` | 400 | 100% | line-height 1.5, 60 to 68ch measure |
| Body | `1rem` | 400 | 100% | line-height 1.6 |
| Label | `.8125rem` | 600 | 100% | sentence case, letter-spacing 0 |
| Readout | `clamp(2.5rem, 1.8rem + 2.4vw, 4rem)` | 520 | 75% (mono) | letter-spacing -.03em, tabular numerals |
| Data and code | `.8125rem` to `.875rem` | 400 to 500 | 87.5% (mono) | line-height 1.55 |

Rules: sentence case everywhere. No tracked-out uppercase eyebrows, no middle-dot meta chains as decoration, and no decorative section numbers. Number only real sequences, such as the pipeline steps. Bold at most one phrase per paragraph. Use tabular numerals for every number that changes.

## Space, radius and layout

- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64, 96 px.
- Radii: `--r-s` 4 px (inputs, code, tags), `--r-m` 8 px (buttons, cards), `--r-l` 14 px (instrument panels).
- Content measure: 1200 px max. Prose stays at 68ch or less. Sections are separated by space and a hairline, not by a card around everything.
- Touch targets are at least 44 px.

## Motion

| Token | Value | Use |
| --- | --- | --- |
| `--dur-fast` | 120 ms | Press, toggle, copy feedback |
| `--dur-med` | 200 ms | State changes, verdict reveal, tab change |
| `--dur-slow` | 300 ms | Panel or dialog entrances |
| `--ease-out` | `cubic-bezier(.16, 1, .3, 1)` | Entrances |
| `--ease-in` | `cubic-bezier(.4, 0, 1, 1)` | Exits |
| `--ease-in-out` | `cubic-bezier(.65, 0, .35, 1)` | In-place state changes |

- **One orchestrated sequence.** The hero helicorder plays the recorded run once on load at its real timing (13.039 s): the pen draws the trace; it ruptures red at 2.103 s when the browser records HTTP 500 and the headline offsets along the fault diagonal; diagnosis starts at 2.615 s, followed by a quiet stretch while the model works (6.9 s, 3,254 tokens); 44 check ticks fill; and the trace settles at 44/44 as the headline realigns. Only `transform`, `opacity` and SVG stroke-dashoffset are animated. Reading and scrolling are never blocked.
- **Recording-based motion is labeled.** Every replay says it is a recording and keeps its real timing. Event times come from `job.json`, and any trace amplitude that is not measured is labeled illustrative.
- Everything else is instant or 120 to 200 ms. There are no infinite pulses except one indicator for work genuinely in flight. No `transition: all`. Hover effects are gated to `(hover: hover) and (pointer: fine)`. No hover lift on non-interactive cards.
- **Playback controls.** The visible “Show final record” button stops the hero sequence immediately, cancels pending playback, and keeps keyboard focus. “Replay the trace” restarts it; repeated stop and replay actions interrupt the previous sequence.
- **Reduced motion.** Show the final record statically, with the rupture and settle drawn as a still diagram. Replay stays static, and enabling reduced motion during playback immediately shows the final record. State changes stay visible (color, mark and text) without movement. The existing global reduced-motion kill switches stay.
- The Inspector's judge drawer keeps its test-pinned 460 ms open and 200 ms close (a documented exception).

## Reusable interactions

- **Button.** On hover (fine pointers only), the border steps from `--control` to `--ink-2`. On press, the border-top becomes `--ink` and the control moves 1 px down (`translateY(1px)`) over 120 ms, with an ease-out curve. The primary button is an ink fill with soot text. A held press dims the fill and keeps the label at 4.5:1 or better.
- **Focus.** A 2 px solid `--ink` outline with a 2 px offset on every control, never transitioned. High-contrast modes keep the existing system-color overrides.
- **Verdict stamp.** A verdict appears with opacity 0 to 1 and scale .98 to 1 over 200 ms, ease-out. Its color and mark (pass, fail or held) arrive together.
- **Dialog and drawer.** Entrance is opacity plus 8 px translate over 300 ms, ease-out. Exit takes 200 ms, ease-in.
- **Tooltip and copy feedback.** Text swap is instant, and the state is announced through the live region.

## Banned chrome (the "AI slop" checklist)

Tracked uppercase mono eyebrow pills; a badge above the h1; middle-dot meta chains; decorative 01 to 08 kickers; arrow or play glyphs in circular wells on buttons; emoji used as icons; neon green or cyan on blue-black; colored glows; colored edge stripes; uniform three-card grids; stat banners without a comparison sentence; gradient text, aurora blobs, glassmorphism, fake window dots; glitch or RGB-split effects; Unknown Pleasures ridgelines; typing effects; scroll-jacking; generic metaphor headlines.

## Copy

The hierarchy is the claim first, then the proof, then the scope. Every number sits next to its scope and a link to its evidence. Use these words: recorded, verified, rejected, blocked. Avoid these words: autonomous, immune system, self-healing, live (for recordings), signed (for checksums), and "every button". The full do-not-claim list is in `docs/HACKATHON_BRIEF.md` and the audits under `docs/audits/`.
