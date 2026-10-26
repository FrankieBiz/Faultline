"use client";

import { useEffect, useRef } from "react";
import type { CheckoutResult } from "@/lib/api";

type Failure = Exclude<CheckoutResult, { kind: "placed" }>;

/**
 * Explains why "Place order" did not produce an order. Rendered as an
 * `alert` and focused on arrival, so the failure is announced, scrolled into
 * view, and captured in failure screenshots.
 */
export function CheckoutFailure({ failure }: { failure: Failure }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, [failure]);

  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="rounded-md border-[1.5px] border-alarm-edge border-l-8 border-l-alarm bg-alarm-wash px-5 py-4 outline-none"
    >
      <p className="text-lg font-extrabold text-alarm">Checkout failed</p>
      <div className="mt-1 space-y-2">
        <FailureBody failure={failure} />
      </div>
    </div>
  );
}

function FailureBody({ failure }: { failure: Failure }) {
  switch (failure.kind) {
    case "failed": {
      const serverError = failure.status >= 500;
      return (
        <>
          <p>
            {serverError
              ? `The store returned HTTP ${failure.status} (${failure.reason}) and didn't confirm an order.`
              : `The store rejected the order with HTTP ${failure.status} (${failure.reason}).`}{" "}
            Your cart is unchanged, so you can place the order again
            {serverError ? "." : " after correcting it."}
          </p>
          {failure.details.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5 text-sm">
              {failure.details.map((detail, index) => (
                <li key={index}>{detail}</li>
              ))}
            </ul>
          ) : null}
        </>
      );
    }
    case "unreadable":
      return (
        <p>
          The store answered HTTP {failure.status}, but the order details couldn&apos;t be read ({failure.message}),
          so this page can&apos;t confirm the order.
        </p>
      );
    case "unreachable":
      return (
        <p>
          The store couldn&apos;t be reached ({failure.message}). Check your connection, then place the order
          again.
        </p>
      );
  }
}
