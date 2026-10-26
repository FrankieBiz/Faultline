"use client";

import Link from "next/link";
import { countItems, useCart, useHydrated } from "@/lib/cart";

/**
 * Header link to checkout with a live item-count badge. The accessible name
 * states the count ("Cart, 2 items") so assistive technology and automated
 * browsers read the same value that is shown visually.
 */
export function CartLink() {
  const cart = useCart();
  const hydrated = useHydrated();
  const count = hydrated ? countItems(cart) : 0;
  const label = count === 1 ? "Cart, 1 item" : `Cart, ${count} items`;

  return (
    <Link
      href="/checkout"
      aria-label={label}
      className="inline-flex min-h-11 items-center gap-2 rounded-md border-[1.5px] border-spruce px-3.5 py-1.5 font-bold transition-colors hover:bg-spruce/5"
    >
      <span>Cart</span>
      <span
        // Re-keying on the revision restarts the bump for each in-page change
        // without animating a cart that was merely restored on page load.
        key={cart.revision}
        aria-hidden="true"
        className={`notebook-paper inline-flex min-w-7 items-center justify-center rounded-full border border-notebook-edge px-2 text-sm leading-6 tabular-nums ${
          count === 0 ? "opacity-60" : cart.revision > 0 ? "motion-safe:animate-badge-bump" : ""
        }`}
      >
        {count}
      </span>
    </Link>
  );
}
