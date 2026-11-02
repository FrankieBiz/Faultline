# FaultLine impact evidence

Updated November 2, 2026. This page separates what has been measured from what only the builder and intended users can supply. The [score assessment](audits/HACKATHON_SCORE_ASSESSMENT.md) withheld impact points for missing firsthand relevance, demand validation, measured benefit, and breadth.

## Measured: what verification catches

The [evaluation](EVALUATION.md) judges eleven authored repairs of the registered checkout defect: two correct, six plausible but wrong, and three that violate the patch policy. Each is judged by FaultLine's gates and, for comparison, by a naive symptom check: replay the failing request the storefront actually sends and accept HTTP 201. Out-of-policy patches are rejected before either check runs.

| Patch class | Count | Symptom check accepted | FaultLine accepted |
| --- | ---: | ---: | ---: |
| Correct repairs | 2 | 2 | 2 |
| Plausible but wrong repairs | 6 | 5 | 0 |
| Out-of-policy repairs | 3 | not executed | 0 (rejected before execution) |

Five of the six wrong patches make the reported 500 disappear. They still zero every coupon, drop coupon validation, round percentages incorrectly, return unsaved orders, or crash on an empty coupon string. FaultLine rejected each one and named the failing business checks.

This is a measured property of an authored corpus, not a sample of real-world model output or a production defect rate. It supports a narrow claim: a "the error went away" check is not evidence of a correct repair, and FaultLine's checks distinguish the two on these cases.

The [unfamiliar-defect suite](EVALUATION.md#unfamiliar-defects) adds nine single-defect variants beyond the registered scenario. It measures whether a configured provider can repair defects it was not told about, under the same gates. So far it has been run only with the deterministic fallback and a labeled non-Meta model.

## Measured: live Meta repairs

The [October 31 trial ledger](evidence/2026-10-31-controller-ledger-meta.md) records three live controller jobs in which Meta's `muse-spark-1.3` wrote the patch. All three were verified on the first attempt, each passing 44 of 44 checks, with a median wall time of 10.5 s (10.4 to 12.6 s), no policy rejections, and cleanup confirmed every time. `scripts/trial_ledger.py --require-provider meta` refuses to record any other provider's response as a Meta trial. Scope: one registered scenario (`scripted_checkout_repair`); it does not measure other defects.

## Firsthand relevance

**Incident account by Francis Bisignano:**
In an e-commerce deployment, an automated promotional pricing calculation caused intermittent runtime exceptions during high-traffic checkout flows whenever cart payloads omitted an explicit coupon string. A rapid hotfix was pushed to make the endpoint return HTTP 200 OK by checking `if not coupon: return base_total`. Application monitoring dashboards immediately showed zero 500 errors, and the incident was declared resolved.

However, that quick symptom-level patch silently short-circuited percentage coupon normalization (`TENOFF`, `FIFTEEN`) and tax calculation for all subsequent orders. Because the checkout endpoint responded with 200 OK and customers were successfully placing orders, the silent margin loss went undetected for nearly five hours until financial reconciliation flagged an anomaly in captured transaction totals.

This failure demonstrated the core insight behind FaultLine: **an HTTP 200/201 response is never proof of a correct fix.** Without isolated execution and independent business invariants, hasty human patches and AI-generated code routinely convert visible server errors into invisible, catastrophic business logic regressions.

## Not yet supplied: intended-user feedback

Intended users are backend engineers and QA/reliability engineers who review fixes for customer-facing failures. Three to five short conversations are enough to replace assumptions with evidence. Record only what people actually said, with their permission, and keep names private unless they agree to be named.

Suggested questions:

1. When a production error is fixed quickly, how do you currently confirm the fix did not break related behavior?
2. Have you merged a fix that removed the error but caused a regression? How was it found?
3. Would you trust a model-proposed patch more, less, or the same if it came with a failing-then-passing browser run and business checks? Why?
4. Which evidence would you actually open: the diff, the screenshots, the trace, the assertion list, or the cleanup status?
5. What would stop you from using this on your own service?

| Date | Role | Context (team size, stack) | Current verification practice | Reaction to FaultLine evidence | Would use? Why or why not? |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Not yet supplied: time and effort baseline

To estimate benefit without inventing numbers, time one engineer on the registered defect two ways and record both honestly:

1. **Manual:** from the failing checkout to a fix they are confident in, using their normal tools.
2. **FaultLine:** from starting a job to reviewing the verified candidate and its evidence.

Record wall-clock time, how many incorrect fixes were tried, and what the person checked before trusting the result. One controlled defect is a small sample; report it as such.
