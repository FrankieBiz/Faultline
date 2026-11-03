# FaultLine Inspector perfection audit

**Scope:** `web/inspector-ui` (Inspector, Judge Evidence Drawer, evaluation corpus explorer, proof export, live job and crawl streaming), the demo pitch flow, and the recorded figures the drawer shows.
**Date:** 2026-11-02 · **Baseline commit:** `0288183` (branch `FrankieBiz/claude-perfection-audit`).
**Companion:** [`UI_AUDIT_CLAUDE.md`](UI_AUDIT_CLAUDE.md) covers the broader design-system review. This audit looks for defects a judge or a live demo would hit.

Severity: **P1** visible defect or inaccurate claim · **P2** accessibility or reliability gap · **P3** polish.

## How this was verified

| Check | Before | After |
|---|---|---|
| `npm run check` in `web/inspector-ui` (`tsc --noEmit` + `next build`) | Pass, exit 0 | Pass, exit 0 |
| `npm run test:inspector` in `tools/browser-runner` | 48 / 48 passed | **50 / 50 passed** (two new regression tests) |
| `npm run typecheck` in `tools/browser-runner` (includes the spec) | — | Pass, exit 0 |
| axe-core 4 (WCAG 2.0/2.1/2.2 A+AA and best practice) on the production build, at 1440×900 and 390×844. Five states each: landing, drawer scorecard, drawer corpus, verified job, running job. | 3 rule failures, in every state | **0 violations in all 10 runs** |
| New regression tests run against the **original** `Inspector.tsx` | — | Both fail as expected. The crawl case reads "Stopped · crawl in progress", and the SSE case records a "reconnecting" label. |
| WCAG contrast of every palette pair, computed by hand. axe skips text drawn over gradients. | — | Lowest pair is `--red` on the green-washed card at **4.91:1**. Every text pair passes AA. |
| Every hard-coded figure in `lib/judge-evidence.ts`, `JudgeEvidence.tsx` and `EvaluationCorpus.tsx` cross-checked against the committed records | — | 4 inaccuracies fixed. Everything else matches (list below). |
| Job SSE and crawl NDJSON paths read against the orchestrator (`app/main.py` `event_stream`, `app/api.py` crawl lock) | — | 2 reliability defects fixed. Cursor and parser confirmed correct. |

The screenshots and axe runs used a scratch Playwright script with the same mocked controller as the spec. Nothing from that harness is committed.

---

## Fixed

### P1 · The judge drawer clipped its own heading
- **Symptom:** the bottom ~8 px of "Judge scorecard & telemetry" (its descenders) was painted over on desktop and mobile. This is the first thing a judge sees after pressing `J`.
- **Cause:** the sticky tab bar masks content with `box-shadow: 0 -28px 0 0 var(--raised)`. That band reaches 28 px up, but the gap above the bar is only 20 px, so the band covered the heading.
- **Fix:** the band now matches the gap, `0 -20px 0 0` (`globals.css:721`).

### P1 · Word spaces collapsed in the corpus verdict cards
- **Symptom:** "False green: the500 is gone", "refused 3 of 3out-of-policy".
- **Cause:** two unrelated rules share the name `.verdict`. The Seam's 28 px verdict text and the corpus cards both match it. The cards inherited `letter-spacing: -0.02em`. Since `em` resolves where the rule is declared, that became a fixed −0.56 px applied to 12.5 px text.
- **Fix:** the Seam rule is scoped to `.side .verdict` (`globals.css:588`).

### P1 · Recorded-evidence copy said more than the records do
| Where | Was | Record | Now |
|---|---|---|---|
| `JudgeEvidence.tsx:86` | "The ledger script refuses any non-Meta response." | `scripts/trial_ledger.py` refuses only when the readiness provider ≠ `--require-provider`. Other responses are labeled, not refused. `IMPACT_EVIDENCE.md:23` has the exact wording. | "…refuses to record any other provider's response as a Meta trial." |
| `EvaluationCorpus.tsx:77` | "27 business checks **in the sandbox**" | The drawer itself says the trusted checks run *outside* the sandbox, and `DEVPOST_SUBMISSION.md:69` agrees. | "27 business checks on the sandboxed build" |
| `judge-evidence.ts:133` | "hid five hours of margin loss" | `IMPACT_EVIDENCE.md:30`: "undetected for **nearly** five hours" | "hid nearly five hours" |
| `judge-evidence.ts:18` | The oracle's 15 "must be refused" checks were out of order, although the comment says they follow `app.http_regression` | `http_regression.py:119-138`: `…unknown_product, unknown_coupon, invalid_coupon_type, client_price, unknown_fields, quantity_missing, quantity_zero…` | Reordered, so the 27-cell strip now matches the oracle |

The comment at `judge-evidence.ts:31` used to say contracts are "in the contract's words". They are paraphrases of `model_adapter.py`, and the comment now says so.

### P2 · Job stream flashed "reconnecting" at the end of every run
- **Cause:** `event_stream` sends a terminal job's last event and then closes the stream. `EventSource` reports that clean close as an error, and `onerror` immediately set `reconnecting` and scheduled a reconnect.
- **Worse case:** if a poll was already in flight, the next poll was up to 1.5 s away. The label could cycle reconnecting → live → reconnecting before then.
- **Fix:** `onerror` now polls the record first, through a new `pollNow` (`Inspector.tsx:268`, `:298`). The `reconnecting` label and the reopen wait for the backoff timer, and a terminal poll cancels that timer. A poll requested while one is in flight now runs as soon as it settles, so it is not dropped.
- **Test:** "a finished run's closed event stream reads complete without flashing reconnecting" (`inspector.spec.ts:1235`). It records every label change with a `MutationObserver`. This is also the first test that delivers a `job_event` over SSE.

### P2 · Stop, then Run again, failed the crawl
- **Cause:** after Stop, the orchestrator holds its single crawl slot until Chromium exits, which can take seconds. A re-run in that window got `409 crawl_in_progress`, and the HUD ended on "Stopped · crawl in progress". That is very likely during a live demo.
- **Fix:** a `409 crawl_in_progress` is now treated as draining (`Inspector.tsx:572`). The HUD shows "The previous crawl is still closing its browser. Retrying (n of 5)…", backs off 1 + 2 + 3 + 4 s, and reports the error only if the slot never frees.
- **Test:** "a re-run while a stopped crawl still holds the engine waits for it instead of failing" (`inspector.spec.ts:708`).

### P2 · Accessibility (axe-core, every state)
- **`link-in-text-block`:** Tailwind's preflight removes link underlines. The store bar's `127.0.0.1:8000` and "Open storefront" links were distinguished from `--ink-2` text by color alone, at 1.91:1. They are now underlined (`globals.css:395`), matching the drawer's link treatment.
- **`scrollable-region-focusable`:** three horizontally scrolling `<pre>` blocks could not be reached by keyboard: the gate payload, the agent snippets and the holdout defect diff. They now take `tabIndex={0}` (`AgentGatePanel.tsx:98`, `:365`; `EvaluationCorpus.tsx:133`), as the existing diff blocks already did.
- **`definition-list`:** the Meta ledger stats had a `<span>` directly inside each `dl > div`. The sub-line is now a second `<dd class="ledger-note">` (`JudgeEvidence.tsx:66-69`). A term may have several values, so this is valid. The ledger test selector was narrowed to match.

### P3 · Polish
- **Mobile drawer tabs** overflowed by a few pixels at 390 px, clipping the selected tab's edge. Tab padding is now 8 px under 760 px (`globals.css:860`).
- **Plurals:** "1 artifacts recorded" and "All artifacts · 1 files" are now singular for one item (`Evidence.tsx:106`, `:400`).
- **Spacing:** the corpus intro paragraph sat about 4 px above the verdict cards. It now has a 16 px gap (`globals.css:786`).

---

## Confirmed correct (no change)

- **Holdout corpus:** all ten defect ids, titles, classes, failing-check lists and displayed diffs match `fixtures/evaluation/cases.json` and the seed files. All 20 DeepSeek trial outcomes match the evidence JSON. That is 18 / 20 verified, with `coupon_case_sensitive` trial 2 verified on attempt 2 and `order_wrong_namespace` rejected twice.
- **Gauntlet:** all 11 rows and the derived figures (5 / 6 false greens, 6 / 6 rejected, 2 / 2 correct, 3 / 3 refused by policy) match `EVALUATION.md` and both October 28 evidence files.
- **Meta ledger:** job ids, wall times (median 10.5 s, range 10.4 to 12.6 s), token counts, 44 / 44 per trial and cleanup 3 / 3 all match `2026-10-31-controller-ledger-meta.md`. The rubric weights 30 / 25 / 20 / 25 match `HACKATHON_BRIEF.md`. All five linked docs exist on `main`.
- **Sandbox claims:** 48 / 48 and 19 / 19 sessions under verified limits; 512 MiB, no swap, 64 tasks, one CPU; 44 assertions = 16 checkout + 1 confirmation + 27 regression.
- **Streaming internals:**
  - The `?after=` cursor matches the orchestrator's `after` query, and events dedupe by `sequence`.
  - No `EventSource` or timer leaks on job change or unmount.
  - The proxy sets `no-cache, no-transform` and `X-Accel-Buffering: no`.
  - The NDJSON crawl parser handles chunk-split lines, a trailing line without a newline, and split UTF-8.
- **Proof export:** shown only for a run that meets every verification condition. It shows no hard-coded claims, and the patch download ends in a newline so `git apply` accepts it.
- **Pitch timing:** the voiceover's "in under seven seconds" matches the retained job's 6,863 ms generation time (`2026-10-28-meta-replay-review.md`). Both cuts run under 180 s.
- **Motion:** `prefers-reduced-motion: reduce` disables every animation and transition, including the drawer slide.

---

## Open: recommended, not changed here

| Sev | Item | Why it was left |
|---|---|---|
| ~~P2~~ | ~~`docs/DEVPOST_SUBMISSION.md:23` and `:34` repeat two of the fixed overstatements.~~ | **Resolved** in the [second-stage pass](#second-stage-pass-2026-11-03). Re-paste the changed sections into Devpost if it already has the old copy. |
| ~~P3~~ | ~~`docs/VOICEOVER_SCRIPT.md` links its video files as `file:///home/frankbiz/.../barnacle/...`.~~ | **Resolved** in the [second-stage pass](#second-stage-pass-2026-11-03). |
| P3 | "Copy patch" does not re-announce on a second click, because the live-region text is unchanged. | Cosmetic for screen readers; clear the text before setting it again. |
| P3 | `aria-label` sits on generic elements: `<pre>` in `Diff` and `.defect-code`, and the holdout `/27` count span. ARIA 1.2 prohibits naming generic roles, although Chromium honors it. | Use `role="region"` with the label, or visually hidden text. |
| P3 | At 390 px the header's five tools wrap to three rows above the hero. | A layout choice; consider collapsing CLI guide and Sound cues into a menu on narrow screens. |
| P3 | Gaps in test coverage: NDJSON split across network chunks, `CrawlInterrupted` mid-stream, and SSE `after=` resume after a real drop. | The code reads correctly; these need a streaming mock rather than `route.fulfill`. |
| P3 | "the retained Meta job" (singular, `JudgeEvidence.tsx:33`). Two retained Meta jobs exist (`3573b32b`, `82ac2dcc`). | The claim holds for both, so it is accurate as written. |

---

## Second-stage pass (2026-11-03)

Branch `FrankieBiz/claude-devpost-demo-perfection`. It covers submission copy, the voiceover, and demo rehearsal tooling. The Inspector UI did not change.

### Submission and voiceover copy

| Where | Was | Record | Now |
|---|---|---|---|
| `DEVPOST_SUBMISSION.md:23` | "The ledger script refuses any non-Meta response." | `IMPACT_EVIDENCE.md:23`, `JudgeEvidence.tsx:86` | "`scripts/trial_ledger.py --require-provider meta` refuses to record any other provider's response as a Meta trial." |
| `DEVPOST_SUBMISSION.md:24` | "a one-line patch in 6.9 s" | `job.json` `generation_ms` 6,863 | The same figure, plus "(6,863 ms recorded generation time)". This is the source of the voiceover's "under seven seconds". |
| `DEVPOST_SUBMISSION.md:34` | "Datadog", "completely broken", "for five hours until accounting caught" | `IMPACT_EVIDENCE.md` § Firsthand relevance names no vendor and says "nearly five hours" and "financial reconciliation" | Restated from the recorded account, with a link to it. The owner TODO for Inspiration is checked. |
| `DEVPOST_SUBMISSION.md:69` | "Trusted browser and HTTP verification run outside the candidate." | `job.json` verification report: 16 checkout + 1 confirmation + 27 regression | Names the 16 / 27 / 1 checks and says they run outside the candidate, against the sandboxed build. This matches `EvaluationCorpus.tsx:77`. |
| `VOICEOVER_SCRIPT.md` video links | `file:///home/frankbiz/.../barnacle/...` | `data/` is gitignored | Repository-relative `../data/footage/...` links, plus a "Footage files" note naming the scripts that produce them. |
| `VOICEOVER_SCRIPT.md` Meta segment (both tracks) | "runs … against 44 independent checks, passing every assertion" | Same verification report | "…passes all 44 independent checks, 27 of them business rules, on the first attempt." |
| `VOICEOVER_SCRIPT.md` gauntlet segment (both tracks) | "reject every single wrong patch" | `EVALUATION.md`: 6 of 6 authored wrong repairs | "reject all six", scoped to the corpus being shown |

`VOICEOVER_SCRIPT.md` now opens with a **Claim sources** table. It maps each spoken figure to its record.

### Rehearsal tooling

- `scripts/rehearse-demo.sh --dry-run` checks tools and readiness, prints the cue sheet, and creates no job. It requires `curl` and `jq` only; `uv` is needed only when a job is created.
- `scripts/rehearse-demo.sh --interactive` pauses for Enter before each beat, and `q` stops the rehearsal. The beats follow the voiceover segments. Without a terminal on stdin it says so and runs unattended, so it cannot hang in CI. Combine both flags to practice narration without touching the controller.
- After a verified job, the rehearsal prints the assertions by group and the generation time, and compares them with the spoken figures. Run against the recorded `3573b32b` job record, it prints `checkout 16, confirmation 1, regression 27` and `6863 ms (under seven seconds)`.
- If the Inspector is unreachable, the rehearsal names the URL it tried and how to start the stack, instead of printing a bare curl error.
- `scripts/start-live-demo.sh --check` (alias `--dry-run`) reports uv, Bubblewrap, cgroup v2, the systemd user session, the port, credential presence (never values), `LIVE_DEMO_REQUIRE_PROVIDER`, and the data directory. Then it exits without syncing or starting anything. It fails if the provider is pinned to `meta` without `META_API_KEY`.
- Neither script's default (no-flag) behavior changed. `deploy/faultline-live.service` and `tests/test_rehearsal.py` still call them that way.

### Verification

| Check | Result |
|---|---|
| `npm run check` in `web/inspector-ui` (`tsc --noEmit` + `next build`, Next.js 16.4.3) | Pass, exit 0 |
| `npm run test:inspector` in `tools/browser-runner` | **50 / 50 passed** (46.7 s) |
| `pytest apps/buggyshop-backend/tests tests` | 328 passed, 23 skipped (platform-specific). This includes `tests/test_rehearsal.py`: 6 existing cases and 4 new ones for dry-run, readiness failure, the no-terminal fallback, and option rejection. |
| `ruff check` and `ruff format --check` (the `make check` scope for `tests` and `scripts`) | Pass |
| `rehearse-demo.sh` run against the recorded `3573b32b` job record through a stub `curl` | Exit 0. Prints `checkout 16, confirmation 1, regression 27` and `6863 ms (under seven seconds)`. |
| `rehearse-demo.sh --dry-run --interactive` under a pseudo-terminal | All five beats wait for Enter. `q` exits 0 with "Rehearsal stopped by presenter". |
| `start-live-demo.sh --check` | Exit 0 on this host, with two warnings: no model credential and no provider pin. Exit 1 when the port is taken, or when `LIVE_DEMO_REQUIRE_PROVIDER=meta` is set without `META_API_KEY`. |

In a fresh worktree, `tests/test_platform_smoke.py` fails three cases with `runner_unavailable` until `npm --prefix tools/browser-runner run build` has run. That comes from the environment, not from this change.

