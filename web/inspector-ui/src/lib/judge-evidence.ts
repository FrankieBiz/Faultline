/**
 * Recorded evidence for the judge drawer. Every figure here is copied from a committed record;
 * keep it in step with the source named beside it rather than editing numbers by hand.
 *
 * - Corpus: fixtures/evaluation/cases.json (checkout-eval-v1) and docs/EVALUATION.md
 * - Repair outcomes: docs/evidence/2026-10-28-evaluation-deepseek-v4-pro.json
 * - Meta ledger: docs/evidence/2026-10-31-controller-ledger-meta.md
 * - Rubric weights: docs/HACKATHON_BRIEF.md
 */

const REPO = "https://github.com/FrankieBiz/Faultline/blob/main";
export const docUrl = (path: string) => `${REPO}/${path}`;

/** The oracle's 27 HTTP business checks, in the order app.http_regression runs them. */
export const ORACLE_CHECKS: { id: string; group: "accept" | "reject" | "read" }[] = [
  ...["missing_coupon", "null_coupon", "empty_coupon", "whitespace_coupon", "tenoff", "fifteen", "normalized_coupon",
    "mixed_cart", "mixed_cart_coupon", "quantity_ten"].map((id) => ({ id: `regression.${id}`, group: "accept" as const })),
  ...["empty_cart", "duplicate_product", "unknown_product", "unknown_coupon", "invalid_coupon_type", "client_price",
    "unknown_fields", "quantity_missing", "quantity_zero", "quantity_eleven", "quantity_negative", "quantity_fraction",
    "quantity_string", "quantity_boolean", "quantity_null"].map((id) => ({ id: `regression.${id}`, group: "reject" as const })),
  ...["unknown_order", "unknown_product_readback"].map((id) => ({ id: `regression.${id}`, group: "read" as const })),
];

/** A repair attempt's recorded result in one trial. */
export type TrialOutcome = "verified" | "verified_on_retry" | "rejected";

export interface HoldoutDefect {
  id: string;
  title: string;
  defectClass: string;
  /** The business rule the defect breaks, paraphrasing the repair contract. */
  contract: string;
  /** The defect against the healthy source: removed lines start with "-", added with "+". */
  change: string[];
  failing: string[];
  /** Two recorded trials with a labeled non-Meta model; see MODEL_RUN. */
  trials: [TrialOutcome, TrialOutcome];
}

const ZERO_DEFAULT = "-    discount = cast(int, discounts.get(coupon_code, 0))";
const ACCEPTS = ["missing_coupon", "null_coupon", "empty_coupon", "whitespace_coupon", "mixed_cart", "quantity_ten"].map((id) => `regression.${id}`);

export const HOLDOUT: HoldoutDefect[] = [
  {
    id: "seeded_missing_coupon", title: "A missing coupon subtracts None", defectClass: "Null handling",
    contract: "A checkout without a coupon has zero discount, and its total equals its subtotal.",
    change: [ZERO_DEFAULT, "+    discount = cast(int, discounts.get(coupon_code))"],
    failing: ACCEPTS, trials: ["verified", "verified"],
  },
  {
    id: "fifteen_float_rounding", title: "FIFTEEN uses float rounding instead of floored cents", defectClass: "Rounding",
    contract: "FIFTEEN takes 15% of the subtotal, truncated to whole cents with integer arithmetic.",
    change: ['-        "FIFTEEN": subtotal * 15 // 100,', '+        "FIFTEEN": round(subtotal * 0.15),'],
    failing: ["regression.fifteen"], trials: ["verified", "verified"],
  },
  {
    id: "coupon_case_sensitive", title: "Coupon codes are not upper-cased", defectClass: "Input normalization",
    contract: "Coupon codes match regardless of case, so tenoff applies TENOFF.",
    change: ['-    coupon_code = (payload.coupon_code or "").strip().upper()', '+    coupon_code = (payload.coupon_code or "").strip()'],
    failing: ["regression.normalized_coupon"], trials: ["verified", "verified_on_retry"],
  },
  {
    id: "coupon_whitespace_untrimmed", title: "Coupon codes are not trimmed", defectClass: "Input normalization",
    contract: "Whitespace around a coupon is ignored, and a blank coupon means no coupon.",
    change: ['-    coupon_code = (payload.coupon_code or "").strip().upper()', '+    coupon_code = (payload.coupon_code or "").upper()'],
    failing: ["regression.whitespace_coupon", "regression.normalized_coupon"], trials: ["verified", "verified"],
  },
  {
    id: "line_total_ignores_quantity", title: "Line totals ignore quantity", defectClass: "Pricing",
    contract: "Each line totals the catalog unit price times its quantity.",
    change: ['-                "line_total_cents": product["price_cents"] * item.quantity,', '+                "line_total_cents": product["price_cents"],'],
    failing: ["regression.mixed_cart", "regression.mixed_cart_coupon", "regression.quantity_ten"], trials: ["verified", "verified"],
  },
  {
    id: "discount_sign_inverted", title: "The discount is added to the total", defectClass: "Pricing",
    contract: "A discount is subtracted from the subtotal, never added to it.",
    change: ["-    total = subtotal - discount", "+    total = subtotal + discount"],
    failing: ["regression.tenoff", "regression.fifteen", "regression.normalized_coupon", "regression.mixed_cart_coupon"],
    trials: ["verified", "verified"],
  },
  {
    id: "discount_first_line_only", title: "The percentage applies to the first line only", defectClass: "Pricing",
    contract: "A percentage coupon applies to the whole cart's subtotal, not only its first line.",
    change: ['-        "TENOFF": subtotal // 10,', '-        "FIFTEEN": subtotal * 15 // 100,',
      '+        "TENOFF": line_items[0]["line_total_cents"] // 10,', '+        "FIFTEEN": line_items[0]["line_total_cents"] * 15 // 100,'],
    failing: ["regression.mixed_cart_coupon"], trials: ["verified", "verified"],
  },
  {
    id: "unknown_coupon_accepted", title: "Unknown coupons are silently accepted", defectClass: "Validation",
    contract: "An unknown coupon is refused with HTTP 400 and creates no order.",
    change: ["-    if coupon_code and coupon_code not in discounts:", '-        raise HTTPException(status_code=400, detail="Invalid coupon code")'],
    failing: ["regression.unknown_coupon"], trials: ["verified", "verified"],
  },
  {
    id: "missing_coupon_key_error", title: "A missing coupon raises KeyError", defectClass: "Null handling",
    contract: "A checkout without a coupon has zero discount; looking it up must never raise.",
    change: [ZERO_DEFAULT, "+    discount = cast(int, discounts[coupon_code])"],
    failing: ACCEPTS, trials: ["verified", "verified"],
  },
  {
    id: "order_wrong_namespace", title: "Orders are stored outside the caller's namespace", defectClass: "Persistence",
    contract: "Each order is stored in the caller's namespace and reads back from it.",
    change: ["-    return create_order(namespace, order)", '+    return create_order("demo", order)'],
    failing: ORACLE_CHECKS.filter((c) => c.group === "accept").map((c) => c.id), trials: ["rejected", "rejected"],
  },
];

/** The recorded unfamiliar-defect run behind HoldoutDefect.trials. */
export const MODEL_RUN = {
  provider: "DeepSeek deepseek-v4-pro",
  note: "Labeled non-Meta model. Meta has not yet been run on this corpus.",
  verified: 18, runs: 20, date: "October 28, 2026",
  source: "docs/evidence/2026-10-28-evaluation-deepseek-v4-pro.md",
};

export type PatchKind = "correct" | "wrong" | "out_of_policy";
/** Eleven candidate repairs of the registered defect, judged by a symptom check and by FaultLine. */
export const GAUNTLET: { id: string; title: string; kind: PatchKind; symptom: boolean | null; faultline: boolean; failing: number | null }[] = [
  { id: "reference_default_zero", title: "Default a missing coupon discount to zero", kind: "correct", symptom: true, faultline: true, failing: 0 },
  { id: "alternative_or_zero", title: "Coalesce a missing discount to zero", kind: "correct", symptom: true, faultline: true, failing: 0 },
  { id: "zero_all_discounts", title: "Set every discount to zero", kind: "wrong", symptom: true, faultline: false, failing: 4 },
  { id: "null_coupon_only", title: "Handle null coupons but not empty strings", kind: "wrong", symptom: true, faultline: false, failing: 2 },
  { id: "silence_type_error", title: "Catch the TypeError and keep a null discount", kind: "wrong", symptom: false, faultline: false, failing: 6 },
  { id: "drop_coupon_validation", title: "Default to zero and remove coupon validation", kind: "wrong", symptom: true, faultline: false, failing: 1 },
  { id: "round_percentages", title: "Rewrite discounts with float rounding", kind: "wrong", symptom: true, faultline: false, failing: 4 },
  { id: "early_return_unsaved", title: "Return early without storing the order", kind: "wrong", symptom: true, faultline: false, failing: 6 },
  { id: "debug_logging_import", title: "Add a logging import while fixing", kind: "out_of_policy", symptom: null, faultline: false, failing: null },
  { id: "out_of_scope_schema", title: "Change the request schema instead", kind: "out_of_policy", symptom: null, faultline: false, failing: null },
  { id: "stale_context", title: "Patch authored against a different revision", kind: "out_of_policy", symptom: null, faultline: false, failing: null },
];

export const RUBRIC: { name: string; weight: number; evidence: string; doc: { label: string; path: string } }[] = [
  { name: "Impact", weight: 30, evidence: "A fix can return 201 and still be wrong. Over 11 authored patches for the seeded checkout defect, a status-only check accepted 5 of 6 wrong fixes; FaultLine accepted none and still accepted both correct ones.",
    doc: { label: "Impact evidence", path: "docs/IMPACT_EVIDENCE.md" } },
  { name: "Use of Meta AI tooling", weight: 25, evidence: "muse-spark-1.3 writes the patch from the business contract and failure evidence, never the bug's name, then independent gates decide it.",
    doc: { label: "Meta trial ledger", path: "docs/evidence/2026-10-31-controller-ledger-meta.md" } },
  { name: "Technical depth", weight: 20, evidence: "Bubblewrap namespaces under kernel-verified cgroup v2 limits, an AST patch policy, 44 checks (16 browser checkout, 27 HTTP business, 1 confirmation), and a hash-pinned corpus.",
    doc: { label: "Evaluation method", path: "docs/EVALUATION.md" } },
  { name: "Demo", weight: 25, evidence: "This Inspector: break the store, repair it in the sandbox, apply the verified fix, and gate a deploy, each step on recorded evidence.",
    doc: { label: "Submission", path: "docs/DEVPOST_SUBMISSION.md" } },
];

export const META_LEDGER = {
  model: "muse-spark-1.3", date: "October 31, 2026", scenario: "scripted_checkout_repair",
  medianSeconds: 10.5, rangeSeconds: [10.4, 12.6] as const, policyRejections: 0,
  trials: [
    { job: "165e0b18", seconds: 10.5, assertions: "44/44", tokens: "1580+1303" },
    { job: "196cc3b6", seconds: 12.6, assertions: "44/44", tokens: "1580+1856" },
    { job: "5fb3c393", seconds: 10.4, assertions: "44/44", tokens: "1573+1825" },
  ],
  source: "docs/evidence/2026-10-31-controller-ledger-meta.md",
};

export const DOCS: { label: string; path: string; note: string }[] = [
  { label: "Devpost submission", path: "docs/DEVPOST_SUBMISSION.md", note: "Every claim beside the record behind it" },
  { label: "Impact evidence", path: "docs/IMPACT_EVIDENCE.md", note: "The authored-patch gauntlet and the three Meta trials" },
  { label: "Evaluation", path: "docs/EVALUATION.md", note: "Corpus, method, results, and how to reproduce them" },
];
