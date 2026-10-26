"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { fetchProduct, type Product } from "@/lib/api";
import { MAX_QUANTITY, addToCart, useHydrated } from "@/lib/cart";
import { formatUsd } from "@/lib/money";
import { useResource } from "@/lib/use-resource";
import { Notice } from "./notice";
import { ProductTag } from "./product-tag";
import { QuantityStepper, parseQuantityText } from "./quantity-stepper";

/** Product detail loaded from `GET /api/products/{id}`. */
export function ProductDetail({ productId }: { productId: string }) {
  const { state, retry } = useResource(`/api/products/${productId}`, (signal) => fetchProduct(productId, signal));

  return (
    <div>
      <Link href="/" className="text-link">
        Back to catalog
      </Link>
      <div className="mt-8">
        {state.status === "loading" ? (
          <p role="status" className="text-moss">
            Loading product…
          </p>
        ) : state.status === "error" ? (
          <div className="max-w-xl">
            <Notice
              tone="error"
              title="This product didn't load."
              action={
                <button type="button" className="btn-secondary" onClick={retry}>
                  Try again
                </button>
              }
            >
              <p>The store returned an error: {state.message}</p>
            </Notice>
          </div>
        ) : state.value === null ? (
          <div className="max-w-xl">
            <h1 className="text-4xl font-extrabold tracking-tight">Product not found</h1>
            <p className="mt-3 text-moss">
              BuggyShop doesn&apos;t stock an item with the ID &ldquo;{productId}&rdquo;. Pick something from the
              catalog instead.
            </p>
          </div>
        ) : (
          <PurchasePanel product={state.value} />
        )}
      </div>
    </div>
  );
}

function PurchasePanel({ product }: { product: Product }) {
  const hydrated = useHydrated();
  const [quantityText, setQuantityText] = useState("1");
  const [confirmation, setConfirmation] = useState<{ text: string; revision: number } | null>(null);
  const quantity = parseQuantityText(quantityText);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (quantity === null) return;
    const result = addToCart(product.id, quantity);
    const text = result.capped
      ? `Your cart now holds ${result.quantity} ${product.name}, the most one order allows.`
      : `${quantity} × ${product.name} added to your cart.`;
    setConfirmation((previous) => ({ text, revision: (previous?.revision ?? 0) + 1 }));
  }

  return (
    <div className="grid items-start gap-10 md:grid-cols-[minmax(0,26rem)_1fr] md:gap-14">
      <ProductTag
        headingLevel="h1"
        size="detail"
        name={product.name}
        price={formatUsd(product.price_cents)}
      />

      <form onSubmit={handleSubmit} aria-label={`Buy ${product.name}`} className="md:pt-10">
        <QuantityStepper value={quantityText} onChange={setQuantityText} disabled={!hydrated} />
        <button type="submit" className="btn-primary mt-6 w-full sm:w-auto" disabled={!hydrated || quantity === null}>
          Add to cart
        </button>
        <div role="status" className="mt-4 min-h-12">
          {confirmation ? (
            <p key={confirmation.revision} className="font-semibold">
              {confirmation.text}{" "}
              <Link href="/checkout" className="text-link">
                Go to checkout
              </Link>
            </p>
          ) : null}
        </div>
        <ul className="mt-6 space-y-1 border-t border-stone pt-5 text-sm text-moss">
          <li>Ships free. No tax is added.</li>
          <li>Limit {MAX_QUANTITY} of each item per order.</li>
        </ul>
      </form>
    </div>
  );
}
