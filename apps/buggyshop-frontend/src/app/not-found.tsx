import Link from "next/link";

/** Fallback for routes BuggyShop does not serve. */
export default function NotFound() {
  return (
    <div className="max-w-xl">
      <h1 className="text-4xl font-extrabold tracking-tight">Page not found</h1>
      <p className="mt-3 text-moss">There&apos;s no page at this address.</p>
      <Link href="/" className="text-link mt-6 inline-block">
        Back to catalog
      </Link>
    </div>
  );
}
