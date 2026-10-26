"use client";

import Link from "next/link";
import { useState } from "react";
import { fetchCatalog, type Product } from "@/lib/api";
import { addToCart, useHydrated } from "@/lib/cart";
import { formatUsd } from "@/lib/money";
import { useResource } from "@/lib/use-resource";
import { Notice } from "./notice";
import { ProductTag } from "./product-tag";

/** Catalog grid loaded from `GET /api/products`, with one-tap add to cart. */
export function Catalog() {
  const { state, retry } = useResource("/api/products", fetchCatalog);

  if (state.status === "loading") {
    return (
      <p role="status" className="mt-14 text-moss">
        Loading the catalog…
      </p>
    );
  }

  if (state.status === "error") {
    return (
      <div className="mt-14 max-w-xl">
        <Notice
          tone="error"
          title="The catalog didn't load."
          action={
            <button type="button" className="btn-secondary" onClick={retry}>
              Try again
            </button>
          }
        >
          <p>The store returned an error: {state.message}</p>
        </Notice>
      </div>
    );
  }

  if (state.value.length === 0) {
    return (
      <div className="mt-14 max-w-xl">
        <Notice tone="info" title="Nothing is for sale right now.">
          <p>Check back once the catalog has been restocked.</p>
        </Notice>
      </div>
    );
  }

  return (
    <section aria-labelledby="catalog-heading" className="mt-14">
      <h2 id="catalog-heading" className="sr-only">
        Catalog
      </h2>
      <ul className="grid gap-8 sm:grid-cols-2 lg:max-w-4xl">
        {state.value.map((product) => (
          <li key={product.id}>
            <CatalogItem product={product} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function CatalogItem({ product }: { product: Product }) {
  const hydrated = useHydrated();
  const [message, setMessage] = useState("");

  function handleAdd() {
    const result = addToCart(product.id, 1);
    setMessage(
      result.capped
        ? `Your cart already holds ${result.quantity}, the most one order allows.`
        : `Added. Your cart has ${result.quantity} ${product.name}.`,
    );
  }

  return (
    <ProductTag
      headingLevel="h2"
      name={
        <Link href={`/product/${encodeURIComponent(product.id)}`} className="rounded-sm hover:underline">
          {product.name}
        </Link>
      }
      price={formatUsd(product.price_cents)}
    >
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn-primary"
          disabled={!hydrated}
          onClick={handleAdd}
          aria-label={`Add to cart, ${product.name}`}
        >
          Add to cart
        </button>
        <Link href={`/product/${encodeURIComponent(product.id)}`} className="text-link">
          Choose quantity<span className="sr-only"> for {product.name}</span>
        </Link>
      </div>
      <p role="status" className="mt-3 min-h-6 text-sm font-semibold">
        {message}
      </p>
    </ProductTag>
  );
}
