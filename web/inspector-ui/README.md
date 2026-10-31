# FaultLine Inspector

Next.js 16 / React 19 developer dashboard on port 4000 for live invariant checks, isolated sandbox repair, and verified delivery to the locally running store.

- **Scenario rail.** Lists every scenario the controller knows. It shows the sandbox repairs the controller admits (the checkout pipeline, or the project runner's selected scenario), `[scenarios.*]` ReproSpecs and `[[invariants.rule]]` rules from `faultline.toml` (re-read on every load, with per-entry config errors), and probes added from the dashboard. Each item shows its latest live result. Scenarios with browser steps are listed but run only in the sandbox.
- **New invariant.** Takes a method, any http(s) URL, an expected status, and an optional JSON body. It saves the probe and checks it live. When the failure reproduces and a registered sandbox repair covers the same route, server error, and source, the dashboard can start that repair automatically. Any other failure is labeled detection only.
- **Live checks.** The controller sends the request from two fresh HTTP sessions through `ReproEngine`. A failure counts only when both sessions fail the same way. Both sessions' statuses, expectations, server errors, and redacted response excerpts are shown. Rules whose URL uses `{port}` ask for the port unless the controller knows it.
- **Sandbox runs.** Readiness, provider identity, the five recorded steps, the before/after seam, patch proposals with gate results, named assertions, events, and downloadable checksummed artifacts. History lists the ten latest runs.
- **Live store bar** (checkout pipeline only; hidden in project mode, where diffs are never applied). Shows whether the running store serves the seeded defect, a fix from a named run, or a hand-modified source. **Apply fix** is enabled only for an opened run whose evidence verifies a fix, and only on the seeded source. **Revert store** restores the seed. **Check checkout live** re-runs the rule that covers the store's checkout route. Nothing is committed, pushed, or deployed.

All controller access goes through `/api/faultline/*`, which allowlists each route. Supply `FAULTLINE_CONTROL_TOKEN` to the server; the UI never receives it. `FAULTLINE_ORCHESTRATOR_URL` defaults to `http://127.0.0.1:9000`. `BUGGYSHOP_PORT` sets the storefront link (default `3000`); the launcher supplies it for alternate ports. Artifact bytes, error types, and SSE replay cursors are preserved by the proxy. Mutation requests from other origins are rejected, and only loopback Host headers are served.

```bash
npm ci
npm run dev
npm run check
```

The root launcher generates a shared session credential and starts the stack. Run `make browser` for the Inspector and storefront browser regression suites.

A verified result refers to the isolated candidate and recorded checks. It does not indicate production deployment or compliance certification.
