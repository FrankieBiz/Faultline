/**
 * Authored preview data for interactive checkout scenarios, not execution evidence.
 * Only NoneType Discount has a registered backend seed. Trace times are playback
 * offsets; code excerpts and receipts describe expected repairs, not live results.
 */

export const CHAOS_SCENARIO_ORDER = [
  "none-type-discount",
  "unregistered-coupon",
  "subtotal-precision-drift",
] as const;

export type ChaosScenarioId = (typeof CHAOS_SCENARIO_ORDER)[number];

export interface CartItem {
  readonly productId: string;
  readonly name: string;
  readonly quantity: number;
  readonly unitPriceCents: number;
  readonly lineTotalCents: number;
}

/** Expected storefront preview; broken server arithmetic belongs in errorToast. */
export interface CustomerCartState {
  readonly currency: "USD";
  readonly items: readonly CartItem[];
  readonly couponInput: string;
  readonly subtotalCents: number;
  /** Unknown coupons cannot be priced until the customer corrects the input. */
  readonly discountCents: number | null;
  readonly totalCents: number | null;
  readonly state: "ready-to-submit";
}

export interface ErrorToast {
  readonly severity: "error";
  readonly title: string;
  readonly message: string;
  readonly httpStatus: 400 | 500;
  readonly errorType: "TypeError" | "KeyError" | "HTTPException";
  readonly fingerprint: string;
  readonly action: "retry-after-repair" | "edit-coupon-after-repair";
}

export interface AgentTraceStep {
  /** Scripted playback offset, not a measured runtime or model latency. */
  readonly atMs: number;
  readonly stage:
    | "baseline"
    | "diagnosing"
    | "patch_validation"
    | "verification"
    | "complete";
  readonly actor: "sentinel" | "repair-model" | "verifier";
  readonly message: string;
}

export interface CodeDiffBeforeAfter {
  readonly filePath: "apps/buggyshop-backend/app/routes/checkout.py";
  readonly language: "python";
  readonly scope: "excerpt";
  readonly before: string;
  readonly after: string;
}

/** Matches the backend order response. All monetary values are integer cents. */
export interface ReceiptOrder {
  readonly id: string;
  readonly line_items: readonly {
    readonly product_id: string;
    readonly quantity: number;
    readonly unit_price_cents: number;
    readonly line_total_cents: number;
  }[];
  readonly subtotal: number;
  readonly discount: number;
  readonly total: number;
}

export type CheckoutOutput =
  | {
      readonly kind: "created";
      readonly httpStatus: 201;
      readonly order: ReceiptOrder;
    }
  | {
      readonly kind: "rejected";
      readonly httpStatus: 400 | 500;
      readonly order: null;
      readonly message: string;
    };

export interface ChaosScenario {
  readonly id: ChaosScenarioId;
  readonly title: string;
  readonly summary: string;
  readonly dataSource: "scripted-preview";
  readonly backend:
    | { readonly kind: "seeded"; readonly scenarioId: "scripted_checkout_repair" }
    | { readonly kind: "preview-only"; readonly scenarioId: null };
  readonly trigger: {
    readonly action: "submit-checkout";
    readonly method: "POST";
    readonly path: "/api/checkout";
  };
  readonly customerCart: CustomerCartState;
  readonly errorToast: ErrorToast;
  readonly agentTrace: readonly AgentTraceStep[];
  readonly codeDiffBeforeAfter: CodeDiffBeforeAfter;
  readonly receiptOutput: {
    readonly beforeRepair: Extract<CheckoutOutput, { kind: "rejected" }>;
    readonly afterRepair: CheckoutOutput;
  };
}

const TWO_MUGS = [
  { productId: "trail-mug", name: "Trail Mug", quantity: 2, unitPriceCents: 1999, lineTotalCents: 3998 },
] as const satisfies readonly CartItem[];

const ONE_MUG = [
  { productId: "trail-mug", name: "Trail Mug", quantity: 1, unitPriceCents: 1999, lineTotalCents: 1999 },
] as const satisfies readonly CartItem[];

const CHECKOUT_TRIGGER = { action: "submit-checkout", method: "POST", path: "/api/checkout" } as const;
const CHECKOUT_FILE = "apps/buggyshop-backend/app/routes/checkout.py";

/** Index by ID for selection; use CHAOS_SCENARIO_ORDER for the scenario picker. */
export const CHAOS_SCENARIOS = {
  "none-type-discount": {
    id: "none-type-discount",
    title: "NoneType Discount",
    summary: "An empty coupon resolves to None and crashes total calculation with HTTP 500.",
    dataSource: "scripted-preview",
    backend: { kind: "seeded", scenarioId: "scripted_checkout_repair" },
    trigger: CHECKOUT_TRIGGER,
    customerCart: {
      currency: "USD",
      items: TWO_MUGS,
      couponInput: "",
      subtotalCents: 3998,
      discountCents: 0,
      totalCents: 3998,
      state: "ready-to-submit",
    },
    errorToast: {
      severity: "error",
      title: "Checkout failed",
      message: "We couldn't calculate your total. Your cart is saved; no order was created.",
      httpStatus: 500,
      errorType: "TypeError",
      fingerprint: "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'",
      action: "retry-after-repair",
    },
    agentTrace: [
      { atMs: 0, stage: "baseline", actor: "sentinel", message: "Submit two Trail Mugs with an empty coupon; expect HTTP 500 and no order." },
      { atMs: 1800, stage: "diagnosing", actor: "repair-model", message: "The missing dictionary entry returns None; cast(int, ...) does not convert it." },
      { atMs: 4000, stage: "patch_validation", actor: "verifier", message: "Review the one-line default of zero in checkout.py; preserve unknown-code validation." },
      { atMs: 6000, stage: "verification", actor: "verifier", message: "Check missing, null, empty, and whitespace coupons, plus TENOFF and FIFTEEN controls." },
      { atMs: 8000, stage: "complete", actor: "verifier", message: "Expected retry: HTTP 201, zero discount, total 3998 cents, exactly one stored order." },
    ],
    codeDiffBeforeAfter: {
      filePath: CHECKOUT_FILE,
      language: "python",
      scope: "excerpt",
      before: `coupon_code = (payload.coupon_code or "").strip().upper()
discounts: dict[str, int | None] = {
    "TENOFF": subtotal // 10,
    "FIFTEEN": subtotal * 15 // 100,
}
if coupon_code and coupon_code not in discounts:
    raise HTTPException(status_code=400, detail="Invalid coupon code")

discount = cast(int, discounts.get(coupon_code))
total = subtotal - discount`,
      after: `coupon_code = (payload.coupon_code or "").strip().upper()
discounts: dict[str, int | None] = {
    "TENOFF": subtotal // 10,
    "FIFTEEN": subtotal * 15 // 100,
}
if coupon_code and coupon_code not in discounts:
    raise HTTPException(status_code=400, detail="Invalid coupon code")

discount = cast(int, discounts.get(coupon_code, 0))
total = subtotal - discount`,
    },
    receiptOutput: {
      beforeRepair: { kind: "rejected", httpStatus: 500, order: null, message: "Total calculation failed; no order created." },
      afterRepair: {
        kind: "created",
        httpStatus: 201,
        order: {
          id: "00000000-0000-4000-8000-000000000001",
          line_items: [{ product_id: "trail-mug", quantity: 2, unit_price_cents: 1999, line_total_cents: 3998 }],
          subtotal: 3998,
          discount: 0,
          total: 3998,
        },
      },
    },
  },
  "unregistered-coupon": {
    id: "unregistered-coupon",
    title: "Unregistered Coupon",
    summary: "An unknown coupon bypasses eligibility validation and raises an unhandled KeyError.",
    dataSource: "scripted-preview",
    backend: { kind: "preview-only", scenarioId: null },
    trigger: CHECKOUT_TRIGGER,
    customerCart: {
      currency: "USD",
      items: TWO_MUGS,
      couponInput: " ghost50 ",
      subtotalCents: 3998,
      discountCents: null,
      totalCents: null,
      state: "ready-to-submit",
    },
    errorToast: {
      severity: "error",
      title: "Coupon check failed",
      message: "We couldn't validate that coupon. Your cart is saved; no order was created.",
      httpStatus: 500,
      errorType: "KeyError",
      fingerprint: "KeyError: 'GHOST50'",
      action: "edit-coupon-after-repair",
    },
    agentTrace: [
      { atMs: 0, stage: "baseline", actor: "sentinel", message: "Submit GHOST50 after trimming and uppercasing; direct dictionary access raises KeyError." },
      { atMs: 1800, stage: "diagnosing", actor: "repair-model", message: "Unknown codes reach pricing without an eligibility check." },
      { atMs: 4000, stage: "patch_validation", actor: "verifier", message: "Review a membership guard before lookup; keep empty coupons at zero discount." },
      { atMs: 6000, stage: "verification", actor: "verifier", message: "Check unknown-code rejection creates no order; valid and empty coupons still succeed." },
      { atMs: 8000, stage: "complete", actor: "verifier", message: "Expected retry: controlled HTTP 400 with no receipt. Customer must remove or correct GHOST50." },
    ],
    codeDiffBeforeAfter: {
      filePath: CHECKOUT_FILE,
      language: "python",
      scope: "excerpt",
      before: `coupon_code = (payload.coupon_code or "").strip().upper()
discounts = {"TENOFF": subtotal // 10, "FIFTEEN": subtotal * 15 // 100}
discount = discounts[coupon_code] if coupon_code else 0
total = subtotal - discount`,
      after: `coupon_code = (payload.coupon_code or "").strip().upper()
discounts = {"TENOFF": subtotal // 10, "FIFTEEN": subtotal * 15 // 100}
if coupon_code and coupon_code not in discounts:
    raise HTTPException(status_code=400, detail="Invalid coupon code")
discount = discounts[coupon_code] if coupon_code else 0
total = subtotal - discount`,
    },
    receiptOutput: {
      beforeRepair: { kind: "rejected", httpStatus: 500, order: null, message: "Coupon lookup failed; no order created." },
      afterRepair: { kind: "rejected", httpStatus: 400, order: null, message: "Invalid coupon code. Remove it or use TENOFF or FIFTEEN before submitting again." },
    },
  },
  "subtotal-precision-drift": {
    id: "subtotal-precision-drift",
    title: "Subtotal Precision Drift",
    summary: "A floating-point discount produces fractional cents and a downstream HTTP 400 rejection.",
    dataSource: "scripted-preview",
    backend: { kind: "preview-only", scenarioId: null },
    trigger: CHECKOUT_TRIGGER,
    customerCart: {
      currency: "USD",
      items: ONE_MUG,
      couponInput: "TENOFF",
      subtotalCents: 1999,
      discountCents: 199,
      totalCents: 1800,
      state: "ready-to-submit",
    },
    errorToast: {
      severity: "error",
      title: "Total rejected",
      message: "The server calculated 1799.1 cents. Checkout requires a total in whole cents; no order was created.",
      httpStatus: 400,
      errorType: "HTTPException",
      fingerprint: "HTTPException: 400: Total must be whole cents",
      action: "retry-after-repair",
    },
    agentTrace: [
      { atMs: 0, stage: "baseline", actor: "sentinel", message: "Submit one 1999-cent mug with TENOFF; a 199.9-cent discount leaves 1799.1 cents and triggers HTTP 400." },
      { atMs: 1800, stage: "diagnosing", actor: "repair-model", message: "Float multiplication breaks the integer-cent contract; discounts must truncate to whole cents." },
      { atMs: 4000, stage: "patch_validation", actor: "verifier", message: "Review integer arithmetic for both promotions; retain the fractional-cent rejection guard." },
      { atMs: 6000, stage: "verification", actor: "verifier", message: "Check TENOFF gives 199 cents off one mug, 399 off two; FIFTEEN gives 299 off one mug." },
      { atMs: 8000, stage: "complete", actor: "verifier", message: "Expected retry: HTTP 201, subtotal 1999, discount 199, total 1800 cents; receipt matches stored order." },
    ],
    codeDiffBeforeAfter: {
      filePath: CHECKOUT_FILE,
      language: "python",
      scope: "excerpt",
      before: `coupon_code = (payload.coupon_code or "").strip().upper()
discounts = {"TENOFF": subtotal * 0.10, "FIFTEEN": subtotal * 0.15}
if coupon_code and coupon_code not in discounts:
    raise HTTPException(status_code=400, detail="Invalid coupon code")
discount = discounts.get(coupon_code, 0)
total = subtotal - discount
if total % 1:
    raise HTTPException(status_code=400, detail="Total must be whole cents")`,
      after: `coupon_code = (payload.coupon_code or "").strip().upper()
discounts = {"TENOFF": subtotal // 10, "FIFTEEN": subtotal * 15 // 100}
if coupon_code and coupon_code not in discounts:
    raise HTTPException(status_code=400, detail="Invalid coupon code")
discount = discounts.get(coupon_code, 0)
total = subtotal - discount
if total % 1:
    raise HTTPException(status_code=400, detail="Total must be whole cents")`,
    },
    receiptOutput: {
      beforeRepair: { kind: "rejected", httpStatus: 400, order: null, message: "Fractional-cent total rejected; no order created." },
      afterRepair: {
        kind: "created",
        httpStatus: 201,
        order: {
          id: "00000000-0000-4000-8000-000000000003",
          line_items: [{ product_id: "trail-mug", quantity: 1, unit_price_cents: 1999, line_total_cents: 1999 }],
          subtotal: 1999,
          discount: 199,
          total: 1800,
        },
      },
    },
  },
} as const satisfies Readonly<Record<ChaosScenarioId, ChaosScenario>>;
