import Inspector from "@/components/Inspector";

export const dynamic = "force-dynamic";

export default function Page() {
  const port = process.env.BUGGYSHOP_PORT || "3000";
  return <Inspector storefrontUrl={`http://127.0.0.1:${port}`} />;
}
