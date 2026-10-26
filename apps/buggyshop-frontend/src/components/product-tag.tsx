import type { ReactNode } from "react";

interface ProductTagProps {
  /** Heading element for the product name; the catalog uses h2, detail pages h1. */
  headingLevel: "h1" | "h2";
  name: ReactNode;
  price: string;
  size?: "catalog" | "detail";
  children?: ReactNode;
}

/**
 * A product presented as a gear hang tag printed on notebook paper. The
 * punched hole is decorative; all meaningful content is plain text.
 */
export function ProductTag({ headingLevel, name, price, size = "catalog", children }: ProductTagProps) {
  const Heading = headingLevel;
  const detail = size === "detail";

  return (
    <div className={`hang-tag notebook-paper flex flex-col ${detail ? "px-8 pt-8 pb-9 sm:px-10" : "px-6 pt-6 pb-7"}`}>
      <span className="tag-hole mx-auto" aria-hidden="true" />
      <Heading
        className={`mt-6 font-extrabold tracking-tight text-balance ${
          detail ? "text-5xl leading-[0.95] sm:text-6xl" : "text-3xl leading-none"
        }`}
      >
        {name}
      </Heading>
      <p className={`mt-5 font-bold tabular-nums ${detail ? "text-3xl" : "text-2xl"}`}>{price}</p>
      {children}
    </div>
  );
}
