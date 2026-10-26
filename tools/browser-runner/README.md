# FaultLine browser runner

Trusted Playwright CLI and oracle for the `scripted_checkout_repair` scenario ([SpecV1 §4, §11](../../docs/SpecV1.md); registry in `shared/config/scenarios.py`). It runs the scenario once in a fresh headless Chromium context, records evidence, judges business assertions, and writes a canonical `ExecutionReport`. It never requests repairs, applies patches, or retries.

## Flow

catalog → Trail Mug → quantity 2 → Add to cart → Go to checkout → shipping details → optional coupon + Apply → Place order. Every request carries `X-Faultline-Case-Id: <case-id>`, so orders land in the case's namespace. Locators use roles and labels only.

## Assertions

Expected order (no coupon or a recognized coupon):

- `checkout.flow_completed`
- `checkout.single_request`
- `checkout.request_payload`
- `checkout.status_201`
- `checkout.order_schema_valid`
- `checkout.order_id_is_uuid`
- `checkout.line_items_match_cart`
- `checkout.subtotal_matches_catalog`
- `checkout.no_coupon_discount_is_zero` (or `checkout.coupon_discount_applied`)
- `checkout.total_matches_subtotal` (or `checkout.total_matches_subtotal_minus_discount`)
- `checkout.confirmation_shown`
- `checkout.confirmation_matches_order`
- `checkout.readback_matches_response`
- `checkout.exactly_one_stored_order`
- `checkout.no_server_errors`
- `checkout.no_browser_exceptions`

An unknown coupon instead expects `checkout.status_400`, `checkout.failure_ui_visible`, and `checkout.no_stored_order`.

Every ID in the registry's `expected_assertions` is emitted. Expected values come from `src/scenario.ts`, written from the business contract and the settled backend interface (`TENOFF` 10%, `FIFTEEN` 15%, unknown coupon 400). Nothing is imported from BuggyShop.

## Report and evidence

`report.json` matches `ExecutionReport` in `shared/contracts/models.py`: `execution_id`, `case_id`, `scenario_id`, `verdict` (`passed`, `failed`, `error`), `duration_ms`, `observations`, `assertions`, `raw_logs`. Failed assertions that observed the same symptom share one `assertion` observation. Network 5xx responses, transport failures, page errors, and runner failures each get their own observation.

The artifacts directory also holds `screenshots/final.png` or `screenshots/failure.png`, `trace.zip`, `network.json` (first-party API traffic, bodies capped at 2 KiB each and 16 KiB total), `console.json`, and `artifacts.json`. The manifest lists each file's ID, relative path, role, size, and SHA-256, so the orchestrator can verify them before registration. Job, phase, attempt, and snapshot identity belong in the orchestrator's execution envelope, not in the runner report.

## CLI

```bash
npm ci && npm run build
node dist/cli.js --base-url http://127.0.0.1:3000 --case-id demo-1 [--coupon TENOFF] [--output-json out/report.json]
```

Other flags: `--artifacts-dir`, `--timeout-ms` (max 20000), `--execution-id`. Run `--help` for details.

Exit codes: `0` passed, `1` assertion failed, `2` runner/infrastructure error, `3` timed out. The canonical verdict has no timeout value, so a timeout reports verdict `error`, exit code `3`, and a `runner_error` observation with `data.reason = "timeout"`. The report is the machine channel; stdout is a human summary.

## Tests

- `npm run check`: typecheck, build, and pure unit tests (`--project=unit`, no browser).
- `npm run test:e2e`: live run against `BUGGYSHOP_BASE_URL` (default `http://127.0.0.1:3000`). Set `FAULTLINE_EXPECTED_OUTCOME=assertion_failed` to confirm the seeded defect reproduces, and `FAULTLINE_COUPON` to enter a coupon.

## Contract status

`src/contracts.ts` mirrors the canonical Pydantic models by hand until TypeScript declarations are generated from `shared/contracts/`; re-export the generated types from that module when they exist. The SpecV1 `--request /input/request.json` invocation is not implemented yet; the CLI flags above cover standalone and development runs.
