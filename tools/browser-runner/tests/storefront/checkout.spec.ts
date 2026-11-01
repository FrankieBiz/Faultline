import { expect, test, type Page } from "@playwright/test";

/** Opens checkout with one $20 mug; every checkout request is captured and rejected with HTTP 400. */
async function openCheckout(page: Page): Promise<unknown[]> {
  const submitted: unknown[] = [];
  await page.addInitScript(() => localStorage.setItem("buggyshop.cart.v1", JSON.stringify({ lines: [{ product_id: "trail-mug", quantity: 1 }] })));
  await page.route("**/api/products", (route) => route.fulfill({ json: [{ id: "trail-mug", name: "Trail Mug", price_cents: 2000 }] }));
  await page.route("**/api/checkout", (route) => {
    submitted.push(route.request().postDataJSON());
    return route.fulfill({ status: 400, json: { detail: "Test submission captured" } });
  });
  await page.goto("/checkout");
  await page.getByLabel("Name", { exact: true }).fill("Test Customer");
  await page.getByLabel("Email", { exact: true }).fill("test@example.com");
  await page.getByLabel("Address", { exact: true }).fill("123 Test Street");
  return submitted;
}

test("coupon edits require review before checkout and submitted price matches preview", async ({ page }) => {
  const submitted = await openCheckout(page);
  const coupon = page.getByLabel("Coupon code", { exact: true });
  const submit = page.getByRole("button", { name: "Place order", exact: true });
  await coupon.fill("TENOFF");
  await page.getByRole("button", { name: "Apply coupon", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Order summary" })).toContainText("$18.00");
  await coupon.fill("FIFTEEN");
  await expect(submit).toBeDisabled();
  await expect(page.getByText("Coupon changed. Choose Apply to update the total before placing your order.")).toBeVisible();
  expect(submitted).toEqual([]);
  await page.getByRole("button", { name: "Apply coupon", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Order summary" })).toContainText("$17.00");
  await submit.click();
  await expect.poll(() => submitted).toEqual([{ items: [{ product_id: "trail-mug", quantity: 1 }], coupon_code: "FIFTEEN" }]);
  await coupon.fill("");
  await expect(coupon).toHaveValue("");
  await expect(submit).toBeDisabled();
  await page.getByRole("button", { name: "Apply coupon", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Order summary" })).toContainText("$20.00");
  await submit.click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[1]).toEqual({ items: [{ product_id: "trail-mug", quantity: 1 }], coupon_code: null });
});

test("a failed checkout focuses its alert before the form accepts input again", async ({ page }) => {
  const submitted = await openCheckout(page);
  // Record where focus is at the moment the form's fieldset re-enables. Input
  // typed after that moment must not be redirected by a late focus move.
  await page.evaluate(() => {
    const fieldset = document.querySelector<HTMLFieldSetElement>('form[aria-label="Checkout"] > fieldset')!;
    const seen: string[] = [];
    Object.assign(window, { focusOnReenable: seen });
    new MutationObserver(() => {
      if (!fieldset.disabled) seen.push(document.activeElement?.getAttribute("role") ?? document.activeElement?.tagName ?? "none");
    }).observe(fieldset, { attributes: true, attributeFilter: ["disabled"] });
  });
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  const alert = page.getByRole("form", { name: "Checkout" }).getByRole("alert");
  await expect(alert).toContainText("Checkout failed");
  await expect(alert).toBeFocused();
  expect(submitted).toHaveLength(1);
  expect(await page.evaluate(() => (window as unknown as { focusOnReenable: string[] }).focusOnReenable)).toEqual(["alert"]);
});
