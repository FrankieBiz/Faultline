# Share cards

The images that represent FaultLine when someone shares a link or posts it: the judge page unfurl on X, LinkedIn, Discord and Slack, the GitHub repository preview, the hackathon gallery thumbnail, and the "201 trap" image posts. Each one is an HTML template in this directory, rendered to PNG by Playwright from the committed records. No number is typed into a template by hand.

## Assets

All are PNG, opaque, sRGB, rendered at device scale 1 into `docs/assets/og/`.

| File | Size | Use |
| --- | --- | --- |
| `faultline-card-v1.png` | 1200x630 | `og:image` and `twitter:image` of `docs/index.html` |
| `faultline-github-1280x640.png` | 1280x640 | GitHub, Settings > General > Social preview (upload by hand; there is no API) |
| `faultline-gallery-1920x1080.png` | 1920x1080 | Hackathon gallery thumbnail (16:9) |
| `faultline-201-trap-1080x1350.png` | 1080x1350 | LinkedIn image post (4:5) |
| `faultline-201-trap-1200x675.png` | 1200x675 | X image post (16:9) |

### The recorded repair (`card.html`: card, GitHub and gallery)

- Headline: "Meta writes the patch. Checks decide."
- Provenance line: "A recorded Meta muse-spark-1.3 repair, drawn at its real timing."
- Two real BuggyShop frames from the same job, split by one diagonal fault: "Checkout failed" with a `HTTP 500` tag, and "Order placed" with a `44 of 44 checks` tag.
- A seismograph of job `3573b32b` with its x axis in real seconds: "HTTP 500 at 2.1 s" in red, a bracket "muse-spark-1.3 proposes the patch, 6.9 s", one green tick per recorded check, and "44 of 44 checks, verified at 13.0 s". The line turns green only after the verification run recorded its result. The footnote says "Trace shape illustrative", because the amplitude and the even tick spacing are not measurements.

### The 201 trap (`trap.html`: LinkedIn and X image posts)

- Headline: "Don't trust the 201." Scope line: "Authored wrong fixes, one checkout route."
- Patch panel: `early_return_unsaved` (labeled "authored test case"), "Returns HTTP 201 Created. Never saves the order." The portrait version shows the fixture's added lines verbatim. Verdict row: "Naive check: did it return 201?", stamped "Accept" in amber (held: let through by a naive check).
- FaultLine panel: "6 of 27 business checks failed." with the six check ids, stamped "Reject" in red.
- Tally: "A naive status check accepted 5 of 6 authored wrong fixes. FaultLine accepted 0." Then "FaultLine still accepted both correct fixes." Source line: `fixtures/evaluation, docs/evidence/2026-10-28-evaluation-*.json`.

Color follows `DESIGN.md`: red is an observed failure (HTTP 500, a failed check, a rejection), amber is what a naive check let through, and green is an observed pass (44 of 44, FaultLine's 0 of 6, the accepted correct fixes).

## Where every number comes from

The templates read these files at render time (`seismogram.js`) and refuse to render if a record stops matching the story.

| On the card | Source |
| --- | --- |
| HTTP 500 at 2.1 s | `docs/replay/3573b32b-.../job.json`: the baseline observation with `kind: http_error` and status 500, timestamp 22:44:01.383Z, minus `job.created_at` 22:43:59.280Z |
| 6.9 s, muse-spark-1.3 | `attempts[0].validation_result.generation_ms` (6,863) and `.model`; the bracket spans the `diagnosing` event (2.615 s) to `patch_validation` (9.521 s) |
| 44 of 44 checks | the verification execution's `report.assertions` (44, all `passed`; 16 checkout, 27 regression, 1 confirmation) |
| verified at 13.0 s | the `completed` event (13.039 s) and `job.outcome: verified` |
| Tick window | the verification execution's `started_at` and `finished_at` (10.746 s to 12.821 s) |
| Frames | `artifacts/e2d4a4a5-db08-4755-a361-d337f61e7244.png` (baseline) and `artifacts/c6b8a6b5-90d7-4abf-a293-7e9237d7bea9.png` (verification) of the same job |
| 5 of 6, 0, both correct fixes | `docs/evidence/2026-10-28-evaluation-deterministic.json` `patches.summary` (`wrong_accepted_by_symptom_check`, `wrong_accepted_by_faultline`, `correct_accepted_by_faultline`); the render also checks that `2026-10-28-evaluation-deepseek-v4-pro.json` agrees |
| 6 of 27, the six check ids | the `early_return_unsaved` case's `failing` list, and the `oracle` field ("27 independent HTTP business checks") |
| Returns HTTP 201, the diff | the case's `symptom_status: 201`, and `fixtures/evaluation/adversarial/early_return_unsaved.diff` verbatim |

The six wrong fixes are authored test cases, not model output. Say so wherever the 201 trap travels. Do not describe them as Meta's or "AI" patches.

## Regenerate

Run these commands from the repository root. The one-time setup runs in a subshell so the renderer keeps the correct working directory.

```sh
(cd tools/browser-runner && npm ci && npx playwright install chromium)   # once
node tools/social/og-card/render.mjs
```

Options: `--out DIR` renders elsewhere (use it to compare), `--only FILE` renders one asset, `--force` writes a draft even when a layout check fails.

The render makes no network requests. Requests go to a made-up origin that is answered from a short allowlist of repository paths (this directory, `docs/assets/fonts/`, the replay, the two evaluation records and the fixture diff); everything else is aborted. Before writing a file, it checks that both web fonts loaded, the records still match, every key element sits 48 px or more from the top and bottom edges and clear of the bottom-left 320x80 (where X overlays the link title), and the PNG is under 1 MB. The og layout also keeps its content inside a centered 940 px column, so a 3:2 center crop (LinkedIn's small preview) never cuts text. Only the drum line runs to the edges.

Rendering is deterministic on one machine: two runs give byte-identical PNGs, and the script prints each file's sha256. Fonts or Chromium versions on another machine can shift pixels, so commit the PNGs rather than rebuilding them in CI.

To look at a template in a browser, serve the repository root (`python3 -m http.server 8000`) and open `http://localhost:8000/tools/social/og-card/card.html?layout=og` (or `layout=gallery`, or `trap.html?layout=portrait` / `landscape`) in a window or device-mode viewport of the asset's exact size.

## Cache busting

Never overwrite a share image that has been published. X caches card images by URL for about a week, LinkedIn keeps the old preview on posts already made, and Discord and Slack cache for about 30 minutes. To change the judge-page card, render it under the next name (`faultline-card-v2.png`: add the entry to `ASSETS` in `render.mjs`), point `og:image`, `og:image:secure_url` and `twitter:image` at it, and leave the old file in place. `tools/browser-runner/tests/showcase/share-card.spec.ts` requires the `-vN` suffix and checks the tags, the limits and every file's dimensions.

After the page deploys: run LinkedIn Post Inspector on `https://frankiebiz.github.io/Faultline/` before the first LinkedIn post, paste the URL into an unsent X post to check the crop and title overlay, and post it once in a private Discord channel.

## Alt text

Use these with the images (both are under X's 420-character limit):

- Recorded repair: "FaultLine share card. Headline: Meta writes the patch. Checks decide. Two real BuggyShop screenshots from one recorded run, split by a diagonal fault: Checkout failed with HTTP 500, and Order placed with 44 of 44 checks. Below, a seismograph of the recorded Meta muse-spark-1.3 repair at its real timing: a red spike at 2.1 s, a quiet 6.9 s while the model proposes the patch, then verified at 13.0 s."
- 201 trap: "Don't trust the 201. An authored wrong fix, early_return_unsaved, returns HTTP 201 Created but never saves the order. A naive check that only asks whether it returned 201 accepts it. FaultLine rejects it: 6 of 27 business checks failed. Across six authored wrong fixes for one checkout route, the naive check accepted 5 and FaultLine accepted 0, while still accepting both correct fixes."

## Files

- `render.mjs`: the renderer and the list of assets.
- `card.html`, `trap.html`: the templates.
- `seismogram.js`: reads the records and draws the trace.
- `shared.css`: tokens from `DESIGN.md` and the self-hosted fonts (Zalando Sans and Martian Mono, OFL; [source versions, licenses and checksums](../../../docs/assets/fonts/README.md)).
