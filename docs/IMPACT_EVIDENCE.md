# FaultLine impact evidence

Updated October 28, 2026. This page separates what has been measured from what only the builder and intended users can supply. The [score assessment](HACKATHON_SCORE_ASSESSMENT.md) withheld impact points for missing firsthand relevance, demand validation, measured benefit, and breadth.

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

## Not yet supplied: firsthand relevance

The brief's "Build for Your World" theme and the impact criterion reward a problem the builder knows firsthand. No agent can supply this, and none has been written here.

**To be written by Francis Bisignano.** Describe a real occasion when a suggested fix, a hotfix, or an AI-generated patch made a failure disappear but broke something else, or when you could not tell whether a fix was correct. Include when it happened, what was affected, how it was found, and what it cost in time. If there is no such occasion, say so plainly and frame the impact around the measured evidence above.

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
