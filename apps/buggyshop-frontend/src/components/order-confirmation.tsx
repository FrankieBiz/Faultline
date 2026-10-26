"use client";

import Link from "next/link";
import { useEffect, useId, useRef } from "react";
import type { Order, Product } from "@/lib/api";
import { formatDiscount, formatUsd } from "@/lib/money";
import { SummaryRow } from "./summary-row";

/** Shipping details the shopper entered. Kept in the browser; never sent to the API. */
export interface ShippingDetails {
  name: string;
  email: string;
  address: string;
}

interface OrderConfirmationProps {
  order: Order;
  shipping: ShippingDetails;
  catalog: readonly Product[];
}

/**
 * Confirmation for a placed order. Every amount comes from the backend's
 * order response, not from the pre-submission preview, so the page shows
 * exactly what the store recorded.
 */
export function OrderConfirmation({ order, shipping, catalog }: OrderConfirmationProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const orderIdLabel = useId();
  const names = new Map(catalog.map((product) => [product.id, product.name]));

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section aria-labelledby="confirmation-heading">
      <h1
        id="confirmation-heading"
        ref={headingRef}
        tabIndex={-1}
        className="text-5xl leading-[0.95] font-extrabold tracking-tight outline-none sm:text-6xl"
      >
        Order placed
      </h1>
      <p className="mt-4 max-w-xl text-lg text-moss">
        Thanks, {shipping.name}. The store recorded your order. No payment was taken.
      </p>

      <div className="mt-10 grid items-start gap-10 lg:grid-cols-[minmax(0,34rem)_1fr]">
        <div className="notebook-paper rounded-md border-[1.5px] border-notebook-edge px-6 py-6 sm:px-8">
          <dl>
            <dt id={orderIdLabel} className="text-sm font-bold">
              Order ID
            </dt>
            <dd aria-labelledby={orderIdLabel} className="mt-1 font-mono text-base break-all">
              {order.id}
            </dd>
          </dl>

          <table className="mt-6 w-full text-left">
            <caption className="sr-only">Items in this order</caption>
            <thead>
              <tr className="border-b-2 border-spruce text-sm">
                <th scope="col" className="py-2 pr-3 font-bold">
                  Item
                </th>
                <th scope="col" className="px-3 py-2 text-right font-bold">
                  Qty
                </th>
                <th scope="col" className="px-3 py-2 text-right font-bold">
                  Price
                </th>
                <th scope="col" className="py-2 pl-3 text-right font-bold">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {order.line_items.map((line) => (
                <tr key={line.product_id} className="border-b border-spruce/20">
                  <th scope="row" className="py-2.5 pr-3 font-semibold">
                    {names.get(line.product_id) ?? line.product_id}
                  </th>
                  <td className="px-3 py-2.5 text-right tabular-nums">{line.quantity}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{formatUsd(line.unit_price_cents)}</td>
                  <td className="py-2.5 pl-3 text-right tabular-nums">{formatUsd(line.line_total_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <dl className="mt-5">
            <SummaryRow label="Subtotal" value={formatUsd(order.subtotal)} />
            <SummaryRow label="Discount" value={formatDiscount(order.discount)} />
            <SummaryRow label="Total" value={formatUsd(order.total)} emphasis />
          </dl>
        </div>

        <div>
          <h2 className="text-xl font-extrabold">Shipping to</h2>
          <address className="mt-2 whitespace-pre-line not-italic">
            {shipping.name}
            {"\n"}
            {shipping.address}
            {"\n"}
            {shipping.email}
          </address>
          <Link href="/" className="btn-primary mt-8">
            Continue shopping
          </Link>
        </div>
      </div>
    </section>
  );
}
