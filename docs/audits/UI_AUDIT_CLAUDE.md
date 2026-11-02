# FaultLine Inspector UI audit

**Scope:** `web/inspector-ui`: `src/app/{layout.tsx,page.tsx,globals.css}`, all 13 files in `src/components/`, and the styling toolchain (`postcss.config.mjs`, Tailwind v4, `next.config.ts`).
**Date:** 2026-11-02 · **Auditor:** independent review, no prior involvement in this UI.
**Baseline commit:** `23ea6f6` (branch `FrankieBiz/claude-ui-auditor`).

## How this was verified

| Check | Result |
|---|---|
| `npm ci && npm run check` in `web/inspector-ui` | **Pass.** `tsc --noEmit` is clean. `next build` (16.4.3, Turbopack) compiled successfully, with routes `ƒ /`, `○ /_not-found` and `ƒ /api/faultline/[...path]`. Exit 0. |
| Production build rendered in headless Chromium (`next start`, port 4517) | Screenshots at 1440, 1024, 820 and 390 px. The orchestrator refused the proxy (no control token), so the renders show the **engine-unreachable** state, which is a real state worth auditing. Idle and error layouts are verified visually. Result states (verdicts, HUD defect, diffs) are audited from source only. |
| `GET /favicon.ico` | **404.** There is no `public/` directory. |
| WCAG contrast for palette pairs | Computed with the WCAG 2.x relative-luminance formula. The figures are quoted below. |
| Web Interface Guidelines (vercel-labs) | Used as the rule checklist for a11y, forms, motion, typography, touch and theming. |

Severity scale: **P0** broken or misleading for real users · **P1** clear defect, fix this cycle · **P2** polish or consistency · **P3** nit.

---

## Verdict

The engineering underneath is careful. Copy is evidence-led, most states have honest wording, `prefers-reduced-motion` is handled, focus rings exist, tabs use roving tabindex, and the dialogs are native `<dialog>`. The surface on top has five problems:

1. **The type system the CSS is designed around never loads.** Every heading, weight (650) and tracking value is tuned for Geist, but the page renders in whatever system font the OS has.
2. **Some semantic bugs a screen reader user will hit**, including a duplicate `id="gate"` that makes a button's description the entire Pre-Flight Gate section.
3. **Too many competing primary actions and live regions.** Hero, Gate, Guided Flow, Mission HUD and Workspace each have a primary CTA, several of them pulse forever, and five live regions talk at once.
4. **The visual language leans on stock "AI dev-tool" tropes**: neon cyan/green/red with glows, emoji icons, the double-bezel pill on every surface, and all-caps 10px tracked micro-labels everywhere. It reads as polished-template rather than designed.
5. **Inconsistent tokens.** There are 21 distinct font sizes, 16 radius values and no hover-capability gating.

None of this blocks the build, but items P0-1 to P0-4 should be fixed before anyone audits the page with a screen reader or on a fresh Linux or Windows machine.

---

## P0: broken or misleading

### P0-1 · The Geist fonts are declared but never loaded
- `src/app/globals.css:35-37` declares `--sans`, `--display` and `--mono` as `"Geist"`, `"Geist Mono"`, …
- No file contains `next/font`, `@font-face` or a `<link>` to the fonts. `rg "next/font|@font-face"` finds nothing.
- **Effect (verified in the screenshots):** on Linux the hero renders in Noto Sans and the mono text in DejaVu/Liberation Mono. Windows will get Segoe UI and Consolas. Only Macs with Geist installed locally see the intended design. The `font-weight: 650` values (`globals.css:157, 188, 324, 328, 675, 695`) snap to 600 or 700 on non-variable fallbacks. The tight tracking of the 68px hero `h1` (`-0.045em`, `:157`) was tuned for Geist's narrow metrics and looks cramped in Noto Sans.
- **Fix:** `import { GeistSans } from "geist/font/sans"; import { GeistMono } from "geist/font/mono";` (or `next/font/local` with the woff2 files), apply their `.variable` classes on `<html>` in `layout.tsx`, and point `--sans`, `--display` and `--mono` at `var(--font-geist-sans)` and `var(--font-geist-mono)`. Keep the current stacks as fallbacks.

### P0-2 · Duplicate `id="gate"` points a button's description at a whole section
- `src/components/AgentGatePanel.tsx:212` renders `<section id="gate" …>` (the Pre-Flight Gate, which is also the header link target `Inspector.tsx:751`).
- `src/components/PackPanel.tsx:49` renders `<p id="gate" className="gate">` for the readiness gate message, and `PackPanel.tsx:36` sets `aria-describedby="gate"` on **Run sandbox repair**.
- `getElementById` returns the first match in DOM order, which is the Gate section. A screen reader focusing "Run sandbox repair" will read the Gate's heading, its lede, the form, and the whole agent snippet as the button's description.
- **Fix:** use `useId()` in PackPanel (as `HeroArena` and `AgentGatePanel` already do), e.g. `${ids}-gate`.

### P0-3 · The green "live" dot contradicts the engine status
- `HeroArena.tsx:92` and `globals.css:156`: `.hero-live` is always green and always pulsing.
- In the 1440px screenshot the kicker shows a pulsing **green** dot while 60px below it the "Repair core" pill shows a **red** dot reading "Engine unreachable", and the header reads "Needs attention" in red.
- The stylesheet's own rule (`globals.css:3-7`: *"Color carries evidence only… green for a verified pass"*) is broken by its first decorative element.
- **Fix:** drive the dot from `readinessTone`, or make it neutral (`--ink-3`) with no pulse. A marketing kicker should not have a status light.

### P0-4 · A diff's add/delete highlighting stops at the viewport edge
- `globals.css:565-568` and `Evidence.tsx:190-199`: `.code` is `overflow: auto`, and each line is a `display: block` span with `white-space: pre`.
- Block spans are only as wide as the scroll container's client width. When a diff line is longer than the panel, the green/red wash and the 2px inset gutter end at the right edge. Scroll sideways and the remaining text sits on a bare background. Reviewers lose the add/delete signal on long lines, which is exactly where it matters.
- **Fix:** make the content box as wide as the longest line. Add `.code { display: grid; }` and `.code span { min-width: max-content; }`, or wrap the lines in an inner `<code style="display:inline-block; min-width:100%">`.

---

## P1: clear defects

### Accessibility and semantics

**P1-1 · Two `<h1>` elements, and the primary content sits outside `<main>`.**
- `HeroArena.tsx:93` has an `<h1>`, and `PackPanel.tsx:23` and `InvariantPanel.tsx:140` each render another `<h1>` inside the workspace.
- `Inspector.tsx:761-777`: the Hero, Mission HUD, Pre-Flight Gate and Demo Playground all sit between `<header>` and `<main>`, with no landmark. `<main id="workspace">` (`:782`) only wraps the scenario detail. The skip link (`:742`, "Skip to the selected scenario") therefore skips the product's main interaction.
- Fix: one `<h1>` (the hero). Demote the workspace titles to `<h2>`, and the sub-headings below them by one level. Wrap everything from the hero to the dashboard in `<main>`, and make the skip link target the hero form or `main`.

**P1-2 · Too many simultaneous live regions.** During one hunt-and-repair, all of these can fire:
- `CrawlerHud.tsx:328`: `role="status"` on the agent status
- `:345`: `role="log" aria-live="polite"` on every ticker step
- `:370`: `role="alert"` on the defect block, which includes the journey ribbon and trail
- `:411`: `aria-live="polite"` on the repair state
- `GuidedFlow.tsx:113`: `aria-live` on the store headline
- `JobResult.tsx:53` and `InvariantPanel.tsx:80`: `aria-live` headings
- `Inspector.tsx:783`: `role="alert"` on every notice

Also, `AgentGatePanel.tsx:252` wraps the whole verdict, **including the multi-paragraph remediation prompt `<pre>`**, in `aria-live="polite"`, so a blocked verdict reads the entire agent prompt aloud.

Fix: keep one polite status line per surface (agent status, gate verdict badge). Remove `aria-live` from the containers. Use `role="status"` instead of `role="alert"` for `idle` and `ok` notices (`Inspector.tsx:783`). Give the ticker `role="log"` without announcing every line, or throttle the announcements.

**P1-3 · Status is shown by color alone.** These marks change only color between pass, fail and in-progress:
- `.pipeline-mark` keeps showing the step number in every state (`Evidence.tsx:115`, `globals.css:513-522`).
- `.rail-dot` (`ScenarioRail.tsx:41`, `globals.css:418-424`).
- `.readiness-dot` (`globals.css:99-104`).
- The `.hud-trail li[data-ok=false]` chips (`globals.css:309`).

Screen reader text exists, but sighted users with color-vision deficiency must tell `#ff4d6a` from `#2dd4ff` and from `#f59e0b` on a 7-8px dot. Fix: add shape. Use ✓/✕/… glyphs in pipeline marks (the flow marks already do this, `GuidedFlow.tsx:139`), a hollow ring for idle, a filled square for failed, and so on.

**P1-4 · Form and control boundaries are too faint (WCAG 1.4.11).**
- `--line-strong` (`rgba(255,255,255,.16)`) on `--well` or `--bg` measures **1.50-1.56 : 1**. It is the only boundary for every input (`.field input`, `globals.css:457`), the URL pills (`:173`, `:686`), the preset chips and the secondary `.btn`. The non-text contrast minimum is **3 : 1**.
- Fix: raise input and control borders to around `rgba(255,255,255,.32)` (≈3 : 1), or add a filled `--raised` background so the shape reads by fill.

**P1-5 · Programmatic flows steal keyboard focus.**
- `Inspector.tsx:641-645`: `select()` always calls `#workspace.focus()`.
- It is called from automated paths the user didn't initiate in the workspace: `settleLive` (`:503`), `quickTest` (`:626`), `repairStore` (`:603`) and `repairFromCrawl` (`:707`).
- A keyboard user who presses **Run Autonomous Exploration** in the hero, or **Break it** in the playground, has focus yanked to `<main>` far below, while the visible action happens in the HUD above.
- Fix: move focus only on direct rail clicks. Automated selection should change state without moving focus.

**P1-6 · Destructive actions have no confirmation or undo.**
- `Inspector.tsx:827`, **Reset environment**: resets the orchestrator environment.
- `InvariantPanel.tsx:179`, **Remove this URL**: deletes the probe *and its check history* (per the notice at `Inspector.tsx:452`).
- `GuidedFlow.tsx:124`, **Revert store**: rewrites source back to the seeded defect.
- Each runs on a single click, and two of them are styled as quiet text links. Fix: confirm with a small `<dialog>`, or make them two-step ("Remove? Confirm / Cancel" inline).

**P1-7 · Touch targets are below 44px, and some below 24px.**
- `.btn.inline-btn` sets `min-height: 0` (`globals.css:135`). It is used for **Quick HTTP Ping** (`HeroArena.tsx:128`), **Check again** (×3), **Check checkout live** and **Revert store**. They come out about 20px tall.
- `.gate-views button` is 26px (`:756`), `.btn.gate-copy` is 30px (`:767`) and `.btn.cmd-copy` is 32px (`:636`).
- Fix: keep the visual size but extend the hit area with `padding-block` plus negative margin, or a `::before` hit-slop. Aim for 44px on touch (`@media (pointer: coarse)`).

**P1-8 · iOS Safari zooms on input focus.**
- Inputs below 16px trigger page zoom on focus in iOS Safari: `.field input/select/textarea` is 14px (`globals.css:458`, `:460` is 13px), `.gate-field input` is 14px (`:693`), and `.arena-field input` bottoms out at 15px (`:182`).
- Fix: `font-size: max(16px, …)` under `@media (pointer: coarse)`.

### Layout and responsive

**P1-9 · The Pre-Flight Gate collides with the Demo Playground.**
- `.preflight` has `padding-top: 28px` and no bottom spacing (`globals.css:649`), and `.playground` starts immediately (`:353`).
- In the 820px and 1440px screenshots the gate's bezel shadow (`--bezel` spreads 7px) is clipped by the playground band, and the rounded tray corners sit flush against a hard horizontal edge.
- Fix: `.preflight { padding-bottom: 40px; }`, or give the playground a top margin.

**P1-10 · The Gate stats grid draws its dividers in the wrong places at mid widths.**
- `globals.css:739-741`: `grid-template-columns: repeat(auto-fit, minmax(110px, 1fr))` with `> div + div { border-left }`.
- With 4 stats (Elements, Actions, Screens, Defects, or "Stopped by") and a `.gate-sim` content box under 440px (viewports from about 961 to 1010px, where the two-column gate grid is narrowest), the 4th cell wraps alone onto row 2. It keeps a stray left border and gets no top divider.
- The ≤760px override (`:821-823`) only handles exactly 2 columns.
- Fix: use `gap: 1px; background: var(--line)` on the grid, with each cell on `--well`, which gives dividers that are correct at any column count. Or fix the column count per breakpoint.

**P1-11 · The integration tabs wrap raggedly at every width.**
- `.gate-tabs` uses `flex-wrap: wrap` and `.gate-tab` uses `flex: 1 1 auto; white-space: nowrap` (`globals.css:772-775`).
- At 1440px "Agent Skill" wraps alone onto a second centered row inside the tab bar. At 390px the result is 1, 2 and 1 tabs per row (screenshots).
- Fix: make the tablist horizontally scrollable (`overflow-x: auto; flex-wrap: nowrap`), or use a 2×2 grid. Shorter labels ("Cursor/Claude", "GitHub CI", "CLI", "Skill") would also fit.

**P1-12 · The sticky scenario rail can't reach its own bottom items.**
- `.rail { position: sticky; top: 20px; }` (`globals.css:400`) has no `max-height` or overflow.
- With more than a handful of scenarios and probes, the rail is taller than the viewport. Sticky positioning then pins its top and hides the bottom entries until the workspace column scrolls to its end.
- Fix: `max-height: calc(100dvh - 40px); overflow-y: auto; overscroll-behavior: contain;`.

**P1-13 · One root cause shows up as five different messages.** Engine-unreachable state, verified in the screenshots:
- Header: "Engine Status: **Needs attention**" (`Inspector.tsx:738`)
- Hero: "Repair core · **Engine unreachable**" (`:736`)
- Playground: "**Store state unavailable**" plus the raw server message and "Check again" (`GuidedFlow.tsx:113,129`)
- Flow step 2: "**Engine needs attention**" (`Inspector.tsx:684`)
- Rail: the raw server message and "Check again" (`ScenarioRail.tsx:84`)
- Workspace: the raw server message again, **with no retry** (`Inspector.tsx:800`)
- History: "Past sandbox runs · **0 recent runs**", which presents a failed load as a real zero (`:810`)

Fix: one engine-down banner under the header with the cause, the fix (`FAULTLINE_CONTROL_TOKEN`) and a single Retry. Other surfaces show a calm disabled state that refers to it. History should say "unavailable", not "0".

### Interaction and copy honesty

**P1-14 · The hero copy promises more than the crawler does.**
- `HeroArena.tsx:95` says: "The agent **clicks every button, fills every form**…".
- The crawler deliberately refuses submit controls and POST forms on hosted previews (commit `4f376ab`; `CrawlerHud.tsx:85` lists `skipped_commit_controls`), and it stops at action, time and screen budgets.
- The Gate copy (`AgentGatePanel.tsx:219-221`) is careful about this. The hero contradicts it. Fix: "The agent explores the page — clicking, filling, and navigating within a budget — and catches…".

**P1-15 · "(Sandbox Verified)" appears on a button before any verification has run.**
- `CrawlerHud.tsx:402`: **Repair with Meta (Sandbox Verified)** is shown before a repair exists.
- A product built around "nothing counts until it's verified" should not label an unstarted action as verified. Fix: "(verified in sandbox)" as a description of what will happen, or put that in the hint line instead of the label.

**P1-16 · Preset chips behave differently in the hero and the Gate.**
- Hero presets **fill** the field (`HeroArena.tsx:117`, `fill()`).
- The visually identical Gate pill **runs immediately** (`AgentGatePanel.tsx:183-186`, `pick()` calls `run()`).
- Both use `aria-pressed`, which is the wrong semantics for both. They are not toggles, and pressing again doesn't un-press. Fix: one behavior (fill, or run with an explicit "Run" affordance on the chip), and drop `aria-pressed` or use `aria-current`.

---

## P2: polish, consistency, design

### Typography

**P2-1 · There is no type scale.** `globals.css` uses **21 distinct px sizes** (9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 15, 15.5, 16, 17, 19, 20, 22, 24, 26, 28, 34) plus several `clamp()`s. Values that differ by half a pixel (12 vs 12.5, 13 vs 13.5, 15 vs 15.5) are visual noise, not hierarchy. Fix: tokens `--fs-micro 11px`, `--fs-small 12.5px`, `--fs-body 15px`, `--fs-lead 17px`, `--fs-h3 20px`, `--fs-h2 28px`, `--fs-display clamp(…)`, and snap everything to them.

**P2-2 · Micro-labels are too small and over-tracked.** There are about 15 uppercase mono labels at 9.5-10.5px with `letter-spacing: 0.16-0.2em`: `.tag`, `.hud-key`, `.store-key`, `.rail-kind` (9.5px, `:406`), `.result-kicker`, `.flow-kicker`, `.gate-kicker`, `.hud-telemetry dt`, `.hud-defect-kicker` and others.
- At 9.5-10px with fallback fonts they blur on 1× displays.
- `.result-kicker` also uppercases timestamps ("LIVE CHECK, 11/2/2026, 14:03:22").
- `.gate-kicker` wraps to two lines on mobile (390px screenshot).
- Fix: 11px minimum, about 0.08em tracking, and fewer of them. Not every block needs an eyebrow pill.

**P2-3 · `--ink-2` and `--ink-3` are nearly the same color.** `#a8aeb8` vs `#959ca8` (`globals.css:16-17`) both read as "grey". The three-level text hierarchy is really two. Fix: push `--ink-3` toward `#7d8592` (it still passes 4.5 : 1 on `--bg` at about 5.2 : 1), or drop a level.

**P2-4 · Tabular numerals are applied to all body text.** `body { font-feature-settings: "tnum" 1; }` (`globals.css:46`) puts tabular figures in prose, which gives uneven word spacing around numbers in sentences. The telemetry, stats and events already set `tabular-nums` locally (`:262`, `:743`, `:285`, `:627`). Fix: remove it from `body`.

**P2-5 · The hero headline is the product name, and the kicker repeats it.** The kicker says "The autonomous immune system for AI coding agents and web apps", then the `<h1>` says "FaultLine Autonomous Immune System" (`HeroArena.tsx:92-93`). The wordmark already names the product. Fix: make the `h1` the value proposition (the Gate's "Nothing ships until the gate clears it." is stronger copy than the hero's), and make the kicker the category.

**P2-6 · Button casing is inconsistent.**
- Title Case: "Run Autonomous Exploration", "Quick HTTP Ping", "Custom Localhost", "Run Pre-Flight Gate", "Apply Verified Fix to Demo Store", "Engine Status:", "Screens Explored", "Agent Status".
- Sentence case: "Custom URL check", "Run sandbox repair", "Run live check", "Check checkout live", "Revert store", "Remove this URL", "Save and check live".
- Pick one (sentence case fits the evidence-first tone) and apply it everywhere. "Enter to unleash" (`HeroArena.tsx:127`) is off-tone for a verification tool.

### Visual language: what reads as templated

**P2-7 · Emoji icons inside a hairline and monospace system.**
- `CrawlerHud.tsx:255-256, 298, 300, 353, 362` use 🌐 ⌨️ 🛒 📋 🖱️ 💥 ✅.
- `AgentGatePanel.tsx:84, 272, 291, 312, 322` use 🤖 ✅ 🛡️ 🛠️.
- The emoji render differently on each OS (Noto Color Emoji on Linux, Segoe on Windows). They clash with the drawn icon language (`CtaIcon` SVGs, CSS lock glyph, speaker bars), and they are the most recognizable "AI-generated dashboard" signal on the page.
- Fix: extend `CtaIcon` with a small 16px stroke set (globe, cursor, keyboard, cart, alert, shield, robot) at `stroke-width: 1.6`.

**P2-8 · The double-bezel pill is applied to every surface.** `var(--bezel)` is used 7 times and `var(--core-hi)` 25 times. The hero field, HUD frame, gate frame, sessions, seam, repair callout, current flow step and dialog all get the same machined double ring. Combined with every chip being a 999px pill, nothing reads as more important than anything else.
- The gate frame nests the bezel tray, the gate panel border, the `.gate-file` bar and the `<pre>`: four concentric bordered boxes, which is the cards-in-cards pattern.
- Fix: reserve the bezel for one hero object per screen (the paste field, or the active mission). Let secondary groups be flat with a hairline.

**P2-9 · The palette is neon with glows.** `#3dffa2`, `#2dd4ff`, `#ff4d6a` and `#f59e0b` (which is Tailwind's stock `amber-500`), each with `box-shadow: 0 0 10px currentColor` or `text-shadow` glows (`:104, 156, 165-167, 265, 283-284, 346, 422-424, 481-482, 731-732`).
- This is the generic "cyber terminal" look, and saturated mint green on near-black vibrates at small sizes.
- Fix: desaturate the status hues slightly (e.g. green `#4ade9b`, red `#f2556b`, a custom amber rather than Tailwind's), and keep glow for a single "live now" element at a time.

**P2-10 · Too much infinite motion.** There are 17 infinite animations:
- `breathe` on the hero repair CTA, apply CTA, Gate run button (pulsing while **idle**, `:697`) and the verdict badge (`:730`)
- `pulse` on the hero kicker dot (`:156`), readiness, rail dots, flow marks, pipeline marks and HUD dots
- the scrolling seismograph (`:238-242`) and the blinking cursor (`:294`)

At idle on desktop, the hero dot, the Gate run button and the Gate seismograph are all moving with nothing happening. Motion should mean "work in flight". Fix: no infinite animation at rest. Breathe only after a verdict that asks for action, and stop after 2-3 cycles (`animation-iteration-count: 3`). (Reduced-motion users are already covered by `globals.css:853-855`.)

**P2-11 · The Mission HUD shows the same click path twice.** The journey ribbon (`CrawlerHud.tsx:379-391`) and the click trail (`:392-396`) render the same path one after the other. Fix: keep the ribbon, which is interactive and has an impact node, and drop the trail chips, or collapse them into the ribbon's `title`.

**P2-12 · There are 16 border-radius values.** They are 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20, 31, 35 and 999px (`globals.css`). Fix: `--r-xs 6`, `--r-sm 10`, `--r-md 14`, `--r-lg 18`, `--r-pill 999`. The 31px and 35px mobile values (`:809`, `:817`) are hand-computed concentric radii that break when padding changes. Use `calc(var(--r-inner) + var(--pad))` instead.

**P2-13 · The idle Gate has a large dead column at desktop.** At 1440px the left (`.gate-sim`) column holds the field, one pill and "Gate armed", then about 200px of empty well beside a tall snippet panel (screenshot). Fix: top-align and cap the snippet height in the idle state (`max-height: 240px`), or show the idle copy and expected-exit legend in the empty space.

### Interaction states

**P2-14 · Hover styles aren't limited to hover-capable devices.** There are 19 `:hover` rules and 0 `@media (hover: hover)` blocks. On touch, buttons keep their hover border after a tap (sticky hover). Fix: wrap the hover rules in `@media (hover: hover) and (pointer: fine)`.

**P2-15 · `.btn.quiet` gains a pill border on hover.** `.btn:hover:not(:disabled)` (specificity 0,3,0, `globals.css:120`) beats `.btn.quiet` (0,2,0, `:133`). Every quiet text button (header tools, Clear, Close, history rows) grows a full pill outline on hover, which is heavier feedback than the primary button gets. If that is intended, document it. Otherwise add `.btn.quiet:hover { border-color: transparent; background: rgba(255,255,255,.05); }`.

**P2-16 · Text in a stale result drops to 2.3 : 1.** `.check[aria-busy="true"] { opacity: .45 }` (`globals.css:468`) takes `--ink-3` text down to **2.27 : 1**. Fix: use opacity 0.7, or desaturate and add a "Re-checking…" overlay label instead.

**P2-17 · Pending flow-step text fails 4.5 : 1.** `.flow-step[data-state="pending"] .flow-button:disabled .flow-copy { opacity: .6 }` (`:377`) puts the detail text at 3.77 : 1 and the status text at **3.21 : 1**. The status line ("Unlocks after a verified repair") is real guidance, not decoration. Fix: dim only the title and mark, and keep the status at full `--ink-3`.

**P2-18 · The CLI guide's Close button scrolls away.** The guide dialog (`CliGuide.tsx:108-114`) scrolls inside `max-height: calc(100dvh - 48px)`, and the head with **Close** scrolls out of view across 9 steps. Fix: `position: sticky; top: 0` on `.guide-head`, with a `--raised` background.

**P2-19 · The header wraps to three rows on phones.** At 390px the tools wrap into three rows above the hero (screenshot): about 110px of chrome. Fix: below 760px, collapse "CLI guide" and "Sound cues" into icon buttons with `aria-label`s, and shorten "Engine Status: Needs attention" to a dot plus "Attention".

**P2-20 · Prose-width snippets are clipped in the Gate code panel.** `.gate-code { white-space: pre }` (`globals.css:759`). The AGENTS.md snippet is prose and cuts off mid-word at desktop width ("…open or update a pull requ"). Fix: `white-space: pre-wrap` for the prose snippets (as `.gate-payload pre` already does at `:762`), and keep `pre` for YAML/CLI.

---

## P3: nits

- **P3-1** · `layout.tsx:15` `className="dark"` does nothing (no `dark:` variants and no custom variant). `antialiased` (`:16`) duplicates `globals.css:47`. Tailwind v4 is imported only for preflight and one `min-h-[100dvh]` utility. Either use it or drop `@import "tailwindcss"` in favor of a 20-line reset. There is no `tailwind.config.*`, which is correct for v4 but worth stating in the README.
- **P3-2** · There is no favicon (`GET /favicon.ico` returns 404) and no `<meta name="theme-color">`. Add `src/app/icon.svg` (the red/green `.glyph` mark) and `export const viewport = { themeColor: "#05070a" }`.
- **P3-3** · `:focus-visible { border-radius: 4px }` (`globals.css:60`) changes the shape of elements that have no radius of their own (links, `summary`) on focus. Use `outline` only. Outlines follow the element's own radius in current browsers.
- **P3-4** · CSS-generated arrows `content: "→"` and `"➔"` (`:308`, `:314`) are announced by some screen readers ("rightwards arrow"). Use `content: "→" / ""`. "➔" (U+2794) can also fall back to emoji presentation.
- **P3-5** · `title`-only tooltips (`CrawlerHud.tsx:333, 385`; `JobResult.tsx:77`; `InvariantPanel.tsx:33`; `Evidence.tsx:340`) aren't reachable on touch or by keyboard.
- **P3-6** · Dates and sizes use bare `toLocaleString()` / `toFixed()` (`Inspector.tsx:817`, `InvariantPanel.tsx:7`, `Evidence.tsx:7-9`, `JobResult.tsx:81`) with three different formats on one page. Use one `Intl.DateTimeFormat` and one `Intl.NumberFormat` (unit: "kilobyte") helper.
- **P3-7** · `job.cleanup_status.replace("_", " ")` (`JobResult.tsx:80`) only replaces the first underscore. Elsewhere the code uses `replaceAll`.
- **P3-8** · "Live updates" shows raw enum values ("live", "reconnecting", "idle") (`JobResult.tsx:82`).
- **P3-9** · The rail group's count is inside `aria-hidden` (`ScenarioRail.tsx:32`), so screen reader users don't hear how many items a group has.
- **P3-10** · Hard-coded element IDs (`scenario-h`, `check-h`, `hud-h`, `hud-blocked`, `store-h`, `flow-1-t`, …) work today because each component renders once. The `id="gate"` collision (P0-2) shows how fragile that is. Use `useId()` throughout.
- **P3-11** · `.gate-link:hover { color: var(--cyan) !important; }` (`globals.css:670`) exists only to beat `.btn.tool:hover`. Raise specificity instead.
- **P3-12** · The Mission HUD ticker (`CrawlerHud.tsx:345`) is a 260px scroll region with no `tabIndex`. Safari keyboard users can't scroll it. (`Evidence.tsx:359` does set `tabIndex={0}` on its log.)
- **P3-13** · The group heading "Your custom website" (`ScenarioRail.tsx:96`) is the singular of a list of URLs, and its kicker is "your urls". Rename it to "Your URLs".
- **P3-14** · External links (`GuidedFlow.tsx:117-118`, `target="_blank"`) give no new-tab cue. The footer "Source" link (`Inspector.tsx:834`) should say where it goes ("Source on GitHub").
- **P3-15** · `.guide-dashboard { margin-top: 30px }` (`globals.css:631`) is a magic number that aligns with the command pills only while each step has one `h3` line. It drifts when a title wraps.

---

## What's already good (keep it)

- Reduced motion is handled globally (`globals.css:853-855`), the quake/flare effects sit behind `prefers-reduced-motion: no-preference` (`:244`, `:660`), and smooth scrolling checks the preference (`CrawlerHud.tsx:310`).
- Native `<dialog>` with `showModal()`, focus moved to the first field, and form errors that focus the offending field with `aria-invalid` and `aria-describedby` (`ProbeDialog.tsx:75-79`).
- A real ARIA tablist with roving tabindex and Arrow/Home/End keys (`AgentGatePanel.tsx:188-196, 345-353`).
- Screen reader text that completes visual-only cues: "Passed:"/"Failed:", step states, ", done" (`Evidence.tsx:116`, `InvariantPanel.tsx:53`, `GuidedFlow.tsx:141`).
- `min-width: 0` and `overflow-wrap: anywhere` are applied consistently, and the 390px render showed no horizontal page overflow.
- The seismograph animates `transform` only, and the CTA halos animate `opacity` only, so both stay on the compositor.
- The copy is honest about uncertainty ("inconclusive, not clean", "a smoke signal… not proof of business logic"). Bring the hero up to the same standard (P1-14).

## Suggested fix order

1. P0-1 fonts · P0-2 duplicate id · P0-3 hero dot · P0-4 diff backgrounds (each under an hour)
2. P1-1 landmarks and headings · P1-2 live regions · P1-5 focus stealing · P1-6 confirmations
3. P1-9 to P1-13 layout and error-state consolidation
4. P2 token pass (type scale, radii, `--ink-3`, hover media, motion budget), then replace the emoji icons
