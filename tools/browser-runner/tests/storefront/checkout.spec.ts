import { expect, test } from "@playwright/test";

test("coupon edits require review before checkout and submitted price matches preview", async ({ page }) => {
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
  await expect(submit).toBeDisabled();
  await page.getByRole("button", { name: "Apply coupon", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Order summary" })).toContainText("$20.00");
  await submit.click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[1]).toEqual({ items: [{ product_id: "trail-mug", quantity: 1 }], coupon_code: null });
});
