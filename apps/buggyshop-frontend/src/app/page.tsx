import { Catalog } from "@/components/catalog";

/** `/`: the BuggyShop catalog. */
export default function HomePage() {
  return (
    <>
      <section aria-labelledby="intro-heading" className="max-w-3xl">
        <h1
          id="intro-heading"
          className="text-5xl leading-[0.92] font-extrabold tracking-tight text-balance sm:text-7xl"
        >
          Two things worth carrying.
        </h1>
        <p className="mt-6 max-w-xl text-lg text-moss">
          A mug for the trailhead and a notebook for the rain. Free shipping, no tax, and no account needed.
        </p>
      </section>
      <Catalog />
    </>
  );
}
