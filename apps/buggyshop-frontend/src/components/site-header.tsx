import Link from "next/link";
import { CartLink } from "./cart-link";

/** Top bar with the BuggyShop wordmark and the cart entry point. */
export function SiteHeader() {
  return (
    <header className="border-b-4 border-spruce">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
        <Link href="/" className="group flex items-baseline gap-2 rounded-sm">
          <span className="text-2xl leading-none font-extrabold tracking-tight">BuggyShop</span>
          <span className="hidden text-sm text-moss sm:inline">Field goods, short list</span>
        </Link>
        <nav aria-label="Store">
          <CartLink />
        </nav>
      </div>
    </header>
  );
}
