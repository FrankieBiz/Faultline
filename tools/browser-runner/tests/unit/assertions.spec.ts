import { expect, test } from "@playwright/test";
import {
  assessCheckout,
  parseDisplayedCents,
  summarize,
  validateOrder,
  type CheckoutEvidence,
} from "../../src/assertions.js";
import { expectCheckout } from "../../src/scenario.js";

const ORDER_ID = "42d7cd06-8edc-4c43-9c22-741f93c3e860";

function order(discount = 0) {
  return {
    id: ORDER_ID,
    line_items: [{ product_id: "trail-mug", quantity: 2, unit_price_cents: 1999, line_total_cents: 3998 }],
    subtotal: 3998,
    discount,
    total: 3998 - discount,
  };
}

function healthyEvidence(coupon: string | null = null, discount = 0): CheckoutEvidence {
  const body = JSON.stringify(order(discount));
  return {
    flow_error: null,
    checkout_requests: [
      {
        method: "POST",
        url: "http://shop.test/api/checkout",
        post_data: JSON.stringify({ items: [{ product_id: "trail-mug", quantity: 2 }], coupon_code: coupon }),
      },
    ],
    checkout_response: { status: 201, body_text: body, request_id: "req-1" },
    ui: {
      confirmation_visible: true,
      failure_alert_visible: false,
      failure_alert_text: null,
      confirmation: {
        order_id: ORDER_ID,
        subtotal: "$39.98",
        discount: discount > 0 ? `−$${(discount / 100).toFixed(2)}` : "$0.00",
        total: `$${((3998 - discount) / 100).toFixed(2)}`,
        lines: [{ name: "Trail Mug", quantity: "2" }],
      },
    },
    order_readback: { status: 200, body_text: body, error: null },
    namespace_orders: { status: 200, body_text: JSON.stringify({ orders: [order(discount)] }), error: null },
    server_errors: [],
    browser_exceptions: [],
  };
}

function seededFailureEvidence(): CheckoutEvidence {
  const evidence = healthyEvidence();
  return {
    ...evidence,
    checkout_response: {
      status: 500,
      body_text: JSON.stringify({ detail: "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'" }),
      request_id: "req-2",
    },
    ui: {
      confirmation_visible: false,
      failure_alert_visible: true,
      failure_alert_text: "Checkout failed The store returned HTTP 500 (Internal Server Error)",
      confirmation: null,
    },
    order_readback: null,
    namespace_orders: { status: 200, body_text: JSON.stringify({ orders: [] }), error: null },
    server_errors: [{ method: "POST", url: "http://shop.test/api/checkout", status: 500 }],
  };
}

function failedIds(evidence: CheckoutEvidence, coupon?: string): string[] {
  return assessCheckout(expectCheckout(coupon), evidence)
    .filter((result) => !result.passed)
    .map((result) => result.id);
}

test.describe("assessCheckout", () => {
  test("a healthy no-coupon order passes every assertion", () => {
    const results = assessCheckout(expectCheckout(undefined), healthyEvidence());
    expect(results.filter((result) => !result.passed)).toEqual([]);
    expect(results.map((result) => result.id)).toEqual([
      "checkout.flow_completed",
      "checkout.single_request",
      "checkout.request_payload",
      "checkout.status_201",
      "checkout.order_schema_valid",
      "checkout.order_id_is_uuid",
      "checkout.line_items_match_cart",
      "checkout.subtotal_matches_catalog",
      "checkout.no_coupon_discount_is_zero",
      "checkout.total_matches_subtotal",
      "checkout.confirmation_shown",
      "checkout.confirmation_matches_order",
      "checkout.readback_matches_response",
      "checkout.exactly_one_stored_order",
      "checkout.no_server_errors",
      "checkout.no_browser_exceptions",
    ]);
  });

  test("covers every assertion the shared scenario registry expects", () => {
    const ids = assessCheckout(expectCheckout(undefined), healthyEvidence()).map((result) => result.id);
    for (const required of [
      "checkout.status_201",
      "checkout.order_id_is_uuid",
      "checkout.line_items_match_cart",
      "checkout.subtotal_matches_catalog",
      "checkout.no_coupon_discount_is_zero",
      "checkout.total_matches_subtotal",
      "checkout.exactly_one_stored_order",
      "checkout.readback_matches_response",
    ]) {
      expect(ids).toContain(required);
    }
  });

  test("a TENOFF order passes when the discount is 399 cents", () => {
    expect(failedIds(healthyEvidence(" tenoff ", 399), " tenoff ")).toEqual([]);
  });

  test("the seeded HTTP 500 fails the order assertions but not the request shape", () => {
    const failed = failedIds(seededFailureEvidence());
    expect(failed).toContain("checkout.status_201");
    expect(failed).toContain("checkout.confirmation_shown");
    expect(failed).toContain("checkout.order_id_is_uuid");
    expect(failed).toContain("checkout.exactly_one_stored_order");
    expect(failed).toContain("checkout.no_server_errors");
    expect(failed).not.toContain("checkout.flow_completed");
    expect(failed).not.toContain("checkout.single_request");
    expect(failed).not.toContain("checkout.request_payload");
  });

  test("a fabricated confirmation without a valid order is rejected", () => {
    const evidence = seededFailureEvidence();
    evidence.ui = healthyEvidence().ui;
    const failed = failedIds(evidence);
    expect(failed).toContain("checkout.confirmation_matches_order");
    expect(failed).toContain("checkout.order_schema_valid");
  });

  test("a constant total that ignores the cart is rejected", () => {
    const evidence = healthyEvidence();
    const wrong = { ...order(), subtotal: 1000, total: 1000 };
    evidence.checkout_response = { status: 201, body_text: JSON.stringify(wrong), request_id: null };
    const failed = failedIds(evidence);
    expect(failed).toEqual(
      expect.arrayContaining([
        "checkout.subtotal_matches_catalog",
        "checkout.total_matches_subtotal",
        "checkout.confirmation_matches_order",
        "checkout.readback_matches_response",
      ]),
    );
  });

  test("a duplicate checkout request is rejected", () => {
    const evidence = healthyEvidence();
    evidence.checkout_requests = [...evidence.checkout_requests, ...evidence.checkout_requests];
    expect(failedIds(evidence)).toEqual(["checkout.single_request"]);
  });

  test("shipping fields leaking into the request body are rejected", () => {
    const evidence = healthyEvidence();
    const [request] = evidence.checkout_requests;
    if (!request) throw new Error("fixture has no request");
    request.post_data = JSON.stringify({ items: [{ product_id: "trail-mug", quantity: 2 }], coupon_code: null, name: "Avery" });
    expect(failedIds(evidence)).toEqual(["checkout.request_payload"]);
  });

  test("an unknown coupon passes when the store rejects it with 400 and shows the failure", () => {
    const evidence: CheckoutEvidence = {
      ...seededFailureEvidence(),
      checkout_requests: [
        {
          method: "POST",
          url: "http://shop.test/api/checkout",
          post_data: JSON.stringify({ items: [{ product_id: "trail-mug", quantity: 2 }], coupon_code: "freeship" }),
        },
      ],
      checkout_response: { status: 400, body_text: '{"detail":"Invalid coupon code"}', request_id: null },
      server_errors: [],
    };
    expect(failedIds(evidence, "freeship")).toEqual([]);
  });

  test("a flow that never reaches checkout fails without throwing", () => {
    const evidence: CheckoutEvidence = {
      flow_error: { step: "open_product", message: "Timeout 7000ms exceeded" },
      checkout_requests: [],
      checkout_response: null,
      ui: null,
      order_readback: null,
      namespace_orders: { status: 200, body_text: '{"orders":[]}', error: null },
      server_errors: [],
      browser_exceptions: [],
    };
    const failed = failedIds(evidence);
    expect(failed[0]).toBe("checkout.flow_completed");
    expect(failed).toContain("checkout.confirmation_shown");
  });
});

test.describe("validateOrder", () => {
  test("accepts the backend order shape", () => {
    expect(validateOrder(order()).ok).toBe(true);
  });

  test("rejects unknown keys, missing keys, and fractional cents", () => {
    expect(validateOrder({ ...order(), extra: true }).ok).toBe(false);
    expect(validateOrder({ ...order(), total: 39.98 }).ok).toBe(false);
    const { discount: _omitted, ...withoutDiscount } = order();
    expect(validateOrder(withoutDiscount).ok).toBe(false);
  });
});

test.describe("parseDisplayedCents", () => {
  test("reads formatted USD amounts", () => {
    expect(parseDisplayedCents("$39.98")).toBe(3998);
    expect(parseDisplayedCents("−$3.99")).toBe(399);
    expect(parseDisplayedCents("$1,234.50")).toBe(123450);
    expect(parseDisplayedCents("Checked at order")).toBeNull();
  });
});

test.describe("summarize", () => {
  test("strips terminal color codes and collapses whitespace", () => {
    expect(summarize("navigating\u001b[2m to \u001b[22m  page\n")).toBe("navigating to page");
  });
});
