import type { Metadata } from "next";
import { ProductDetail } from "@/components/product-detail";

export const metadata: Metadata = {
  title: "Product details",
};

interface ProductPageProps {
  params: Promise<{ id: string }>;
}

/** Decodes a route segment, keeping the raw text if it is not valid percent-encoding. */
function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** `/product/[id]`: product details, quantity selection, and add to cart. */
export default async function ProductPage({ params }: ProductPageProps) {
  const { id } = await params;
  return <ProductDetail productId={decodeSegment(id)} />;
}
