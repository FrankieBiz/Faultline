# FaultLine

**A browser finds the checkout failure. A model proposes a patch. Independent checks decide whether it works.**

FaultLine is a controlled source-repair prototype for the Meta Global AI Developer Hackathon. It targets one reproducible Python checkout defect: buying without a coupon produces an HTTP 500. A successful repair must complete the same browser journey and preserve coupon, pricing, validation, and order-storage behavior.

The result is a **verified candidate with downloadable evidence**. FaultLine does not deploy to production, route live traffic, or claim compliance certification.

![Actual Inspector showing a failed baseline and 44 passing candidate assertions in explicitly labeled deterministic mode](docs/assets/inspector.png)

Recorded local workflow evidence; this screenshot does not represent a live Meta trial.

## Run it

Requires Linux with working unprivileged user namespaces and Bubblewrap (`bwrap`), Git, Python 3.13 via `uv`, and Node.js 24+. On Fedora, if Bubblewrap is missing: `sudo dnf install bubblewrap`. The controller fails closed when its execution requirements are unavailable.

```bash
make setup
make check
./scripts/start-demo.sh
```

Open [the Inspector](http://127.0.0.1:4000). Alternate ports can be set with `BUGGYSHOP_API_PORT`, `FAULTLINE_PORT`, `BUGGYSHOP_PORT`, and `INSPECTOR_PORT`. The launcher binds services to loopback, generates a session control credential if needed, and retains job history. It reports occupied ports instead of killing their owners. Ctrl+C stops its owned processes.

| Service | URL |
| --- | --- |
| Inspector | http://127.0.0.1:4000 |
| Seeded storefront | http://127.0.0.1:3000 |
| Seeded API | http://127.0.0.1:8000 |
| Controller | http://127.0.0.1:9000 |

To use Meta generation, supply `META_API_KEY` through the server environment or an ignored local `.env`. Optional settings are `META_BASE_URL` and `META_MODEL_NAME` (default `muse-spark-1.3`). Never put credentials in browser code. The startup probe reports the actual provider and availability.

Without model credentials, the adapter explicitly identifies itself as `deterministic-checkout-v1`. This is useful for local verification; **it is not a Meta model trial**. Configured provider failures do not silently select that fallback.

```bash
./scripts/rehearse-demo.sh
```

The rehearsal exits unsuccessfully for failed, cancelled, interrupted, timed-out, or unverified jobs. Success requires a reproduced failure, a passing candidate execution, and confirmed cleanup. The live fixture stays seeded so another run can reproduce the same defect.

## What the gates check

1. Reproduce the seeded checkout failure in a fresh real Chromium session.
2. Correlate the HTTP error with observed server failure evidence.
3. Ask the configured provider for a schema-bound, single-file unified diff.
4. Reject stale source hashes, wrong paths, malformed hunks, oversized changes, syntax errors, and forbidden imports/capabilities. Limits: 16 KiB diff, 32 KiB source, 100 changed lines.
5. Apply the candidate to a fresh detached worktree from the pinned fixture commit. Export application files separately from tests and reference solutions.
6. Execute the candidate inside the restricted runtime. Run the browser journey and independent HTTP business assertions, retaining real screenshots, Playwright traces, request logs, and reports.
7. Verify execution identity and artifact hashes, then confirm resource cleanup before recording a verified result. Cleanup failure quarantines further admission.

Static AST inspection and Git worktrees are policy and source-management tools. The runtime provides process isolation. Passing this bounded suite is evidence for the tested fixture behavior, not a proof that arbitrary code is safe.

## Scope and limits

- One registered live scenario: `scripted_checkout_repair`.
- Pricing uses integer cents; coupons are `TENOFF` and `FIFTEEN`.
- Additional chaos scenarios are explicitly authored previews, not live backend defects.
- No continuous production monitoring, Sentry/GitHub integration, rollout, or automatic production deployment.
- No measured customer adoption, revenue saved, recovery SLA, or externally awarded judging score.
- Local checks, contained browser execution, and live Meta inference are separate verification claims. See [the review](docs/QUALITY_REVIEW.md) for the latest evidence and remaining release work.

## Repository

| Path | Responsibility |
| --- | --- |
| [apps/buggyshop-backend](apps/buggyshop-backend) | Seeded FastAPI fixture and protected business inputs |
| [apps/buggyshop-frontend](apps/buggyshop-frontend) | Accessible storefront and runtime backend proxy |
| [services/repair-orchestrator](services/repair-orchestrator) | Durable admission, model adapter, patch policy, runtime, cleanup |
| [tools/browser-runner](tools/browser-runner) | Trusted Playwright journey, assertions, and evidence |
| [web/inspector-ui](web/inspector-ui) | Readiness, job results, diffs, and evidence inspection |
| [shared](shared) / [fixtures](fixtures) | Canonical contracts, scenario, and pinned source provenance |
| [scripts](scripts) | Dependency setup, supervised startup, reconciliation, rehearsal |

`make check` runs Python lint/format/type checks and tests, fixture provenance, storefront lint/type/build, runner type/build/unit tests, Inspector type/build, and Python distribution builds. `make browser` runs Inspector browser regressions; `make integration` requires actual isolated Chromium checks. See the service documentation for runtime integration verification.

## Hackathon materials

[Event brief](docs/HACKATHON_BRIEF.md), [project status](docs/PROJECT_STATUS.md), [submission draft](docs/DEVPOST_SUBMISSION.md), [video storyboard](docs/VIDEO_STORYBOARD.md), [technical dossier](docs/SUBMISSION.md).

The official event pages list submission on November 4, 2026 at 9 PM ET, subject to organizer changes ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon); retrieved October 27, 2026). Preserved webinar materials in `meta-provided/` are immutable.

Built by Francis Bisignano (`FrankieBiz`).
