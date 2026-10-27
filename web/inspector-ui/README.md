# FaultLine Inspector

Next.js 16 / React 19 interface on port 4000 for controlled browser QA and verified source repair.

The Inspector displays actual readiness, provider identity, job state, patch proposals, named assertions, events, and downloadable artifacts. Authored scenario previews are labeled separately. No displayed preview is execution evidence.

All controller access goes through `/api/faultline/*`. Supply `FAULTLINE_CONTROL_TOKEN` to the server; the UI never receives it. `FAULTLINE_ORCHESTRATOR_URL` defaults to `http://127.0.0.1:9000`. Artifact bytes, error types, and SSE replay cursors are preserved by the proxy. Mutation requests from other origins are rejected.

```bash
npm ci
npm run dev
npm run check
```

The root launcher generates a shared session credential and starts the stack. Run `make browser` for the Inspector browser regression suite.

A verified result refers to the isolated candidate and recorded checks. It does not indicate production deployment or compliance certification.
