# FaultLine evaluation results

- Classification: `deterministic_fallback_no_model_call`
- Provider: `deterministic` · model `deterministic-checkout-v1`
- Runtime: `isolated-backend` · seed `44b2a13b4125`
- Corpus: `checkout-eval-v1` · sha256 `3e404f36c845`
- Oracle: app.http_regression (27 independent HTTP business checks)
- Aggregate limits: 19 of 19 backend sessions ran in a verified cgroup v2 scope (512 MiB, 64 tasks, 100% CPU, no swap)
- Window: 2026-10-28T10:27:00.774868+00:00 to 2026-10-28T10:27:09.242662+00:00

The deterministic fallback makes no model call. It only knows the registered defect, so these results test the gates, not model generalization.

## Unfamiliar defects

Verified 1 of 10 runs: 1 on the first attempt, 0 after policy, start-up, or verification findings were sent back, and 0 after a retry that followed a provider fault or a proposal-format rejection.

| Trial | Case | Baseline failures | Attempts | Outcome |
| ---: | --- | ---: | ---: | --- |
| 1 | `seeded_missing_coupon` | 6 | 1 | verified |
| 1 | `fifteen_float_rounding` | 1 | 1 | model error |
| 1 | `coupon_case_sensitive` | 1 | 1 | model error |
| 1 | `coupon_whitespace_untrimmed` | 2 | 1 | model error |
| 1 | `line_total_ignores_quantity` | 3 | 1 | model error |
| 1 | `discount_sign_inverted` | 4 | 1 | model error |
| 1 | `discount_first_line_only` | 1 | 1 | model error |
| 1 | `unknown_coupon_accepted` | 1 | 1 | model error |
| 1 | `missing_coupon_key_error` | 6 | 1 | model error |
| 1 | `order_wrong_namespace` | 10 | 1 | model error |

Outcomes: {'model_error': 9, 'verified': 1}. Repair attempts: 10. Total tokens: not reported. Median generation: 0.0 ms.

## Candidate patches for the registered defect

The naive symptom check (replay the incident request and require HTTP 201) accepted 5 of 6 incorrect patches. FaultLine accepted 0. FaultLine accepted 2 of 2 correct patches; policy rejected 3 of 3 out-of-policy patches before execution.

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
| `debug_logging_import` | out of policy | reject | n/a | reject | 0 |
| `out_of_scope_schema` | out of policy | reject | n/a | reject | 0 |
| `stale_context` | out of policy | reject | n/a | reject | 0 |

These results cover an authored corpus for one checkout route. They are not a benchmark of arbitrary applications, and a verified candidate is not a deployment.
