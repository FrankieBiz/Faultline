# FaultLine evaluation

Updated October 28, 2026. This page describes how FaultLine is evaluated beyond its single demo defect, and reports the recorded results. It answers two questions from the [score assessment](HACKATHON_SCORE_ASSESSMENT.md):

1. Do the gates distinguish correct repairs from repairs that only make the reported error disappear?
2. Can a configured model repair defects it was not told about, under the same gates and feedback loop?

Results describe an authored corpus for one checkout route in one fixture application. They are not a benchmark of arbitrary applications or a production defect rate.

## Corpus

The corpus lives in [`fixtures/evaluation/`](../fixtures/evaluation). Every file is content-addressed in `cases.json`. Verification fails closed if any byte changes (`make provenance`). The controller never imports corpus code; it executes only inside the isolated runtime.

**Unfamiliar defects.** The registered seeded defect plus nine single-defect variants of the checkout route. Each variant was derived from the healthy source with one change, and each fails a specific set of the oracle's 27 checks:

| Case | Defect class | Defect | Failing checks |
| --- | --- | --- | ---: |
| `seeded_missing_coupon` | null handling | Registered defect: a missing coupon subtracts `None` | 6 |
| `fifteen_float_rounding` | rounding | FIFTEEN uses float rounding instead of floored cents | 1 |
| `coupon_case_sensitive` | input normalization | Coupon codes are not upper-cased | 1 |
| `coupon_whitespace_untrimmed` | input normalization | Coupon codes are not trimmed | 2 |
| `line_total_ignores_quantity` | pricing | Line totals ignore quantity | 3 |
| `discount_sign_inverted` | pricing | The discount is added to the total | 4 |
| `discount_first_line_only` | pricing | The percentage applies to the first line only | 1 |
| `unknown_coupon_accepted` | validation | Unknown coupons are silently accepted | 1 |
| `missing_coupon_key_error` | null handling | A missing coupon raises `KeyError` | 6 |
| `order_wrong_namespace` | persistence | Orders are stored outside the caller's namespace | 10 |

**Candidate patches.** Eleven diffs for the registered defect: two correct repairs, six plausible repairs that make the reported 500 disappear but break the contract, and three that violate the patch policy (a module import, a different file, and a stale revision).

## Method

- **Isolation.** Every variant and candidate runs as a fresh backend through `IsolatedRuntime.backend_session`. This uses the same Bubblewrap namespace profile and aggregate cgroup v2 scope (512 MiB, no swap, 64 tasks, one CPU) as controller jobs. The harness refuses to start unless the aggregate-limit enforcement probe passed. Each report records how many sessions ran under kernel-verified limits.
- **Oracle.** `app.http_regression` runs 27 independent HTTP business checks: ten successful checkouts covering coupons, normalization, mixed carts and quantity, fifteen rejected inputs that must create no order, and two not-found reads. Expected values are authored from the business contract, never imported from candidate code.
- **Unfamiliar-defect loop.** The provider receives the source, the failing checks as a test report, and bounded backend logs, all marked untrusted. It never sees the oracle code or the defect's name. A proposal must pass the adapter contract and the patch policy, then the patched candidate is measured in a fresh backend. If any gate rejects attempt 1, its findings go to attempt 2. A case is *verified* only when all 27 checks pass.
- **Symptom check.** For comparison, a naive check replays the incident request the storefront actually sends (two Trail Mugs, `coupon_code: null`) and accepts HTTP 201. This models "the error went away".

## Results

### What verification catches

Recorded on October 28, 2026 under both providers below, with identical results each time:

| Patch | Kind | Policy | Symptom check | FaultLine | Failing checks |
| --- | --- | --- | --- | --- | ---: |
| `reference_default_zero` | correct | pass | accept | accept | 0 |
| `alternative_or_zero` | correct | pass | accept | accept | 0 |
| `zero_all_discounts` | wrong | pass | accept | reject | 4 |
| `null_coupon_only` | wrong | pass | accept | reject | 2 |
| `silence_type_error` | wrong | pass | reject | reject | 6 |
| `drop_coupon_validation` | wrong | pass | accept | reject | 1 |
| `round_percentages` | wrong | pass | accept | reject | 4 |
| `early_return_unsaved` | wrong | pass | accept | reject | 6 |
| `debug_logging_import` | out of policy | reject | not run | reject | — |
| `out_of_scope_schema` | out of policy | reject | not run | reject | — |
| `stale_context` | out of policy | reject | not run | reject | — |

The symptom check accepted 5 of 6 wrong patches. FaultLine accepted none, accepted both correct patches, and rejected all three out-of-policy patches before execution. `null_coupon_only` is the clearest case. It handles the storefront's `null` coupon, so the original browser journey succeeds, but an empty or whitespace coupon still crashes checkout.

### Unfamiliar defects

| Provider | Classification | Runs | Verified | First attempt | On retry | Evidence |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Deterministic fallback (no model call) | `deterministic_fallback_no_model_call` | 10 | 1 | 1 | 0 | [summary](evidence/2026-10-28-evaluation-deterministic.md) |
| DeepSeek `deepseek-v4-pro` (not Meta), two trials | `openai_compatible_model_not_meta_hosted` | 20 | 18 | 17 | 1 | [summary](evidence/2026-10-28-evaluation-deepseek-v4-pro.md) |
| Meta `muse-spark-1.3` | — | not run | — | — | — | requires `META_API_KEY` |

The deterministic fallback knows only the registered defect. It reports `unsupported_fallback_source` for the other nine, as designed. Its row shows that the harness does not invent repairs.

DeepSeek repaired eight of the nine unfamiliar defects in both trials, and the registered defect in both. All 48 backend sessions ran in kernel-verified scopes, and every baseline reproduced exactly its recorded failures. Details from the [full record](evidence/2026-10-28-evaluation-deepseek-v4-pro.json):

- **The gates rejected wrong model output.** In both trials, `order_wrong_namespace` first hit the 120-second provider timeout, and the second proposal still failed all ten successful-checkout checks. Neither patch was counted as a repair.
- **Specific feedback enabled a repair.** In trial 2, the first proposal for `coupon_case_sensitive` miscopied the 64-character source hash. The adapter rejected it as `proposal_base_mismatch`, and the retry, told exactly that, was verified.
- **Recounting mattered.** In 6 of the 18 verified runs, the model's diff declared wrong hunk line counts. Recounting fixed the metadata without touching content, and the strict policy then accepted the diff. Each record keeps the model's original diff.
- **Usage.** The run made 23 model calls using 126,860 tokens, with a median generation time of 40.6 seconds. That exceeds the controller's 45-second per-attempt budget often enough that this model would need a longer budget for controller jobs.

Two earlier complete development runs used intermediate code: one before hunk recounting, and one before proposal errors had specific codes. They verified 7 of 10 and 8 of 10. They are not reported as results because the code differed, and with this little data the differences between runs do not establish cause.

**Why a non-Meta model appears here.** No Meta credential was configured during this review. A real model was needed to show that the harness, feedback loop, and gates behave correctly on live model output. The project's agent instructions permit DeepSeek for evaluation passes, and it was called with `META_REASONING_EFFORT=none`, `META_RESPONSE_FORMAT=json_object`, and `META_TIMEOUT_SECONDS=120`. Every record identifies it as `openai-compatible`. None of these results are Meta results or count toward the Meta tooling criterion.

## Reproduce

```bash
make provenance                                   # corpus hashes
./scripts/evaluate.sh --suite all                 # deterministic unless a provider is configured
META_API_KEY=… ./scripts/evaluate.sh --suite holdout --repeat 2   # or set it in an ignored .env
```

Each run writes `results.json` and `summary.md` under `data/evaluations/`, checkpointing after every case. Reports record the provider and model that answered, tokens, generation time, every attempt's diff, any recounted hunk headers alongside the model's original diff, failing checks before and after, the feedback each retry received, and the aggregate limits of every session.
