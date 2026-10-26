import { expect, test } from "@playwright/test";
import { SCENARIO_ID, expectCheckout, normalizeCoupon } from "../../src/scenario.js";

test("scenario ID matches the shared registry", () => {
  expect(SCENARIO_ID).toBe("scripted_checkout_repair");
});

test.describe("coupon normalization", () => {
  test("treats missing, empty, and whitespace-only coupons as none", () => {
    expect(normalizeCoupon(undefined)).toBeNull();
    expect(normalizeCoupon(null)).toBeNull();
    expect(normalizeCoupon("")).toBeNull();
    expect(normalizeCoupon("   \t")).toBeNull();
  });

  test("trims and upper-cases nonempty coupons", () => {
    expect(normalizeCoupon(" tenoff ")).toBe("TENOFF");
  });
});

test.describe("checkout expectations", () => {
  test("two mugs without a coupon cost 3,998 cents with no discount", () => {
    expect(expectCheckout(undefined)).toEqual({
      kind: "order",
      normalized_coupon: null,
      status: 201,
      line_items: [{ product_id: "trail-mug", quantity: 2, unit_price_cents: 1999, line_total_cents: 3998 }],
      subtotal: 3998,
      discount: 0,
      total: 3998,
    });
  });

  test("TENOFF rounds the discount down to 399 cents", () => {
    const expectation = expectCheckout(" tenoff ");
    if (expectation.kind !== "order") throw new Error("expected an order");
    expect(expectation.discount).toBe(399);
    expect(expectation.total).toBe(3599);
  });

  test("FIFTEEN rounds the discount down to 599 cents", () => {
    const expectation = expectCheckout("FIFTEEN");
    if (expectation.kind !== "order") throw new Error("expected an order");
    expect(expectation.discount).toBe(599);
    expect(expectation.total).toBe(3399);
  });

  test("unknown coupons must be rejected with 400", () => {
    expect(expectCheckout("FREESHIP")).toEqual({ kind: "rejected", normalized_coupon: "FREESHIP", status: 400 });
  });
});
