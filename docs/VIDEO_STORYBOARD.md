# FaultLine: three-minute evidence-led demo

Every cue below shows something that is either **live** (recorded during the take on the bundled demo store) or **retained** (a committed recording, captioned with its date and job). Never narrate a retained clip as live, never narrate the deterministic fallback as Meta, and never cut a historical replay in where a live result was expected.

**Rehearsal stack.** Bundled BuggyShop only; no external app is needed. Use free ports, for example the coordinator's rehearsal ports:

```bash
BUGGYSHOP_API_PORT=8760 FAULTLINE_PORT=9760 BUGGYSHOP_PORT=3760 INSPECTOR_PORT=4760 ./scripts/start-demo.sh
```

Without `META_API_KEY` the local repair is the labeled deterministic fallback (`deterministic-checkout-v1`). Its caption must say "not a Meta trial". The Meta repair in this video is the retained October 28 recording, backed by the October 31 trial ledger.

## Cue sheet (≤ 180 s)

| Time | Source | Picture | Narration | On-screen caption |
| --- | --- | --- | --- | --- |
| 0:00–0:12 | Live | Storefront on `:3760`: two Trail Mugs, coupon left empty, **Place order**, the red "Checkout failed" banner with HTTP 500 | "Leave the coupon empty and this checkout crashes. The homepage is fine, so nobody gets paged." | Live local run · deliberately seeded defect in the bundled demo store |
| 0:12–0:35 | Live | Terminal: `./faultline gate http://127.0.0.1:3760 --json`. Hold on `"verdict": "DEPLOYMENT_BLOCKED"`, `exit 1`, the `failure` (HTTP 500 on POST /api/checkout), the reproduction trail, and `agent_remediation_prompt` | "Before an agent ships, the gate crawls the preview. It is a deterministic crawler, not a model. It hits the 500 at Place order, blocks with exit 1, and hands the agent the exact steps and a fix prompt." | Live · deterministic Playwright crawler (heuristics, no model) |
| 0:35–1:05 | Retained | Judge page, **Play the recorded Meta repair**: timeline, before screenshot, the one-line diff, the model's verbatim explanation, 44 / 44 checks | "Here Meta's muse-spark-1.3 writes the patch from the business rules and the failure evidence. It is never told the bug. This retained job verified 44 of 44 checks in 13 seconds end to end, and three more live trials on the same scenario all verified on the first try." | Retained recording · Meta muse-spark-1.3 · job 3573b32b, Oct 28 2026 · 3 of 3 live trials, Oct 31 ledger (one scenario) · not live |
| 1:05–1:30 | Live | Inspector on `:4760`: the Mission HUD's repair on the caught defect, stages running, then "Fix verified: 44/44 assertions passed in the Bubblewrap sandbox" and the run's resource limits | "Locally, without a key, the same pipeline runs with a labeled deterministic patch. The candidate runs in a namespaced sandbox under kernel-checked memory, task, and CPU limits. The sandbox only confines it; the checks decide if it is right." | Live local · deterministic fallback, not a Meta trial |
| 1:30–1:50 | Retained | Judge page, **Try to fool the gates**: pick `early_return_unsaved` (and optionally `zero_all_discounts`) | "Why the checks matter: this wrong patch returns 201 but never saves the order. A status check ships it. FaultLine's authored business checks reject it, along with every other wrong patch in the corpus." | Recorded Oct 28 corpus · deterministic and DeepSeek runs · not Meta |
| 1:50–2:20 | Live | Inspector: **Apply Verified Fix to Demo Store**, the live re-check `HTTP 201 · defect gone`. Terminal: re-run the gate; hold on `exit 0`, `"stop_reason": "exhausted"`, and the summary's "This does not establish business completeness." | "Apply writes the verified fix to the demo store, and only the demo store. Checkout works again, and the re-gate passes: it explored until nothing was left to try and found no defect. That is a smoke signal for the flows it reached, not a proof that every price is right." | Live · Apply targets the bundled demo store only · clean = exploration finished, explored flows only |
| 2:20–2:35 | Live | Inspector: the run's evidence (screenshots, trace, report download, cleanup confirmed), then **Revert store** restoring the seeded defect | "Every run keeps a checksummed evidence bundle, and cleanup must succeed before the next job. Revert puts the seeded bug back. Nothing was deployed or merged." | Live · nothing deployed; evidence is a checksum, not a signature |
| 2:35–2:52 | Static | Judge page limits section, "What this does not claim" | "The limits: one seeded route, single-file diffs, no auto-deploy, a shared-kernel sandbox with no seccomp, and Meta measured on one scenario. Meta on the full unfamiliar-defect corpus is the next measurement." | Limits as stated on the judge page |
| 2:52–3:00 | Static | End card: judge page and source links | "FaultLine: repairs you can inspect, and a gate your agents can obey." | frankiebiz.github.io/Faultline · github.com/FrankieBiz/Faultline |

### If a live cue does not go as planned

- **The re-gate is inconclusive** (`stop_reason` `max_actions` or `timeout`, exit 1, `incomplete_crawl`): film it as inconclusive, or re-run with a higher `--max-actions` / `--timeout` on camera. Do not cut to the judge page's clean replay; that run predates `stop_reason` and is captioned as historical.
- **The first gate does not hit the 500**: show what it reported. The crawler leaves the optional coupon empty on purpose; if it stops elsewhere, that is the result.
- **The local repair is rejected or times out**: show the rejection and its findings. Do not substitute the retained Meta replay as if it were this run.
- **A Meta key is configured**: the Inspector names Meta only when readiness reports the Meta Model API; caption the 1:05 cue from what it displays.

### Claims to keep straight while narrating

- Independently authored business assertions catch semantic regressions. The kernel sandbox confines execution; it never proves pricing or correctness by itself.
- Apply supports the bundled local demo store only, not an arbitrary repository or production.
- The crawler is deterministic heuristics; Meta generates the source patch.
- A clean gate is a bounded smoke signal for the explored flows, not full deployment proof.
- Durations: the retained job took 13.0 s; the ledger's three trials took 10.4 to 12.6 s (median 10.5 s). Do not imply every job takes 13 s or that a replay is real time unless it is.
- No recovery-time, uptime, avoided-loss, ROI, certification, or score claims.
- AuraScale (the blocked replay on the judge page) is an external scratch app outside this repo. It is optional historical footage, never a required live step.

Before recording: `make check`, `make browser`, the contained runtime integration check, and `./scripts/rehearse-demo.sh` against the rehearsal Inspector (`FAULTLINE_INSPECTOR_URL=http://127.0.0.1:4760`). Disclose any cut or speed-up and keep the original durations.

## Footage

Browser footage and a silent, captioned rough cut are generated by scripts, so they can be regenerated after any UI change. Output goes to `data/footage/<timestamp>/` (ignored by Git). The scripts produce no audio: **narration is recorded by the owner** over the rough cut.

**What must be running.** The recorder checks these before it opens a browser and never starts or stops the stack.

- The demo stack, on any free ports: `BUGGYSHOP_API_PORT=8700 FAULTLINE_PORT=9700 BUGGYSHOP_PORT=3700 INSPECTOR_PORT=4700 ./scripts/start-demo.sh`. Without `META_API_KEY` it uses the labeled deterministic fallback.
- `docs/` over HTTP. `--serve-docs PORT` serves it for the duration of the recording; otherwise pass `--docs-url`.
- For clip 05 only, a live repair service whose allowed origins include the docs origin.

**Regenerate.**

```bash
./scripts/record-footage.sh --stack-ports 3700,4700,8700,9700 --serve-docs 8770
./scripts/assemble-footage.sh   # newest data/footage/*/, or pass a directory
```

`--only 01,03` records a subset. Pages are recorded at 1920x1080 with CSS zoom 1.2 so text stays legible (`--zoom 1` for native size). `--help` lists every option. The assembler needs `ffmpeg` (libx264, or OpenH264 as in Fedora's build), `jq`, and an installed TTF/OTF font found through `fc-match` (Inter, then Liberation Sans or DejaVu Sans).

**Clip 05 against the deployed Meta live service**, once it exists. Record all clips in one run so the assembler sees them together, and use the public judge page so the service's default allowed origin applies. Each recording uses one of the service's per-visitor hourly runs.

```bash
./scripts/record-footage.sh --stack-ports 3700,4700,8700,9700 \
  --docs-url https://frankiebiz.github.io/Faultline/ --live https://<live-service-host> [--live-defect <id>]
./scripts/assemble-footage.sh
```

The assembler puts clip 05 in the rough cut only when the service's run record has `classification` `meta_model` and every attempt's provider is `meta`. Otherwise it writes `05-live-break-it-validation.mp4`, captioned "Pipeline validation only … NOT a Meta run", and leaves it out of the cut.

| Clip | What it shows | Provenance (caption) |
| --- | --- | --- |
| `01-storefront-crash` | Local storefront: two Trail Mugs, empty coupon, Place order, the "Checkout failed" banner with the HTTP 500 `TypeError` | Recorded locally against the seeded fixture; a deliberately planted defect |
| `02-recorded-meta-repair` | Judge page: the recorded repair played at its recorded 13.0 s timing, with timeline and before/after screenshots, then the patch, the model's verbatim explanation, and the recorded facts | Genuine Meta `muse-spark-1.3` evidence (job `3573b32b`, October 28, 2026), captioned as a replay, not a live run |
| `03-gates` | Judge page gate explorer: `zero_all_discounts`, `null_coupon_only`, `early_return_unsaved` | Recorded evaluation results from the October 28 deterministic and DeepSeek corpus runs; not Meta |
| `04-inspector-run` | Inspector: readiness and patch source, Run sandbox repair, live stages, verified result, before/after, proposed patch, evidence, run details | Caption follows the patch source the Inspector displays. Without `META_API_KEY`: "Local run with the deterministic fallback: not a Meta trial" |
| `05-live-break-it` | Judge page with `?live=`: plant a bug, the live run, verdict, and diffs | Model and provider from the live service's run record; only a Meta run joins the rough cut |

**Rough cut.** Order: 01, 02, 05 (Meta only), 04, 03, then a 5-second end card with the source and judge-page links. Clip 02 stands in for the proposal, diff, and candidate rows above, as a labeled retained recording; clip 04 covers Inspector readiness, steps, evidence, and cleanup; clip 03 covers the gate-value table. Segments are trimmed to the recorder's start and end marks with 0.35 s fades; nothing is sped up. `rough-cut.txt` lists each segment's source range and captions for re-editing, and `clips/` holds the trimmed, uncaptioned H.264 clips. A non-Meta clip 05 is never exported uncaptioned. The first cut (October 29, 2026) runs 2:12, which leaves room to hold shots longer under narration.

The scripted clips predate the gate cues above (0:12 and 1:50) and the Apply / Revert cue; record those terminal and Inspector segments live during the take and place them per the cue sheet.

Owner steps: record narration; once the Meta live service is deployed, record clip 05 against it and reassemble; if `META_API_KEY` is configured for the local stack, re-record clip 04 so its caption names the Meta run. Check every caption before publishing.
