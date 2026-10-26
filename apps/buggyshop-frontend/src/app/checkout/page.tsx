import type { Metadata } from "next";
import { CheckoutView } from "@/components/checkout-view";

export const metadata: Metadata = {
  title: "Checkout",
};

/** `/checkout`: cart review, shipping details, coupon, and order placement. */
export default function CheckoutPage() {
  return <CheckoutView />;
}
