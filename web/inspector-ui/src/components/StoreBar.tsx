import type { StoreStatus, Tone } from "@/lib/faultline-api";

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function headline(store: StoreStatus): { tone: Tone; text: string } {
  if (store.state === "seeded") return { tone: "bad", text: "Running the seeded checkout defect" };
  if (store.state === "patched") return { tone: "ok", text: `Running the verified fix from run ${store.applied_job_id?.slice(0, 8)}` };
  if (store.state === "modified") return { tone: "warn", text: "Source changed outside FaultLine" };
  return { tone: "warn", text: "Store source not found" };
}

/**
 * Delivery for the locally running store. Apply writes a verified diff to the
 * working-tree source the store hot-reloads; revert restores the seed. Nothing
 * is pushed or deployed.
 */
export default function StoreBar(props: {
  store: StoreStatus | null; error: string | null; storefrontUrl: string;
  /** A run whose evidence verifies a fix, or null when none is open. */
  verifiedJobId: string | null;
  busy: boolean; applying: boolean; reverting: boolean; checking: boolean;
  onApply: () => void; onRevert: () => void; onRetry: () => void;
  /** Runs the live rule that covers the store's checkout route, when one is declared. */
  onCheckLive: (() => void) | null;
}) {
  const { store, error, storefrontUrl, verifiedJobId, busy, applying, reverting, checking, onApply, onRevert, onRetry, onCheckLive } = props;
  const state = store ? headline(store) : null;
  const canApply = store?.state === "seeded" && verifiedJobId !== null && !busy;
  const canRevert = store !== null && store.state !== "seeded" && store.state !== "missing" && !busy;
  const hint = !store ? null
    : store.state === "patched" ? `Applied${store.applied_at ? ` at ${clock(store.applied_at)}` : ""}. Revert to make the store fail again.`
    : store.state === "modified" ? "The file matches neither the seed nor a FaultLine fix. Revert to restore the seed."
    : store.state === "missing" ? `${store.target_file} is missing from the working tree.`
    : verifiedJobId ? `Applies run ${verifiedJobId.slice(0, 8)}'s verified diff to ${store.target_file}.`
    : "Apply unlocks after a sandbox repair verifies a fix.";

  return (
    <section className="store" data-tone={state?.tone ?? "idle"} aria-labelledby="store-h">
      <div className="shell store-row">
        <div className="store-status">
          <p className="store-key">Live store</p>
          <h2 id="store-h" aria-live="polite">{state?.text ?? (error ? "Store state unavailable" : "Reading store state…")}</h2>
          {store ? (
            <p className="store-meta">
              <code>{store.target_file}</code> served at <a href={store.url} target="_blank" rel="noreferrer">{store.url.replace(/^https?:\/\//, "")}</a>
              {" "}<a href={storefrontUrl} target="_blank" rel="noreferrer">Open storefront</a>
            </p>
          ) : error ? (
            <p className="store-meta">{error} <button type="button" className="btn quiet inline-btn" onClick={onRetry}>Check again</button></p>
          ) : null}
        </div>
        <div className="store-actions">
          <button type="button" className="btn primary" onClick={onApply} disabled={!canApply} aria-describedby={hint ? "store-hint" : undefined}>
            {applying ? "Applying fix…" : "Apply fix"}
          </button>
          <button type="button" className="btn" onClick={onRevert} disabled={!canRevert} aria-describedby={hint ? "store-hint" : undefined}>
            {reverting ? "Reverting…" : "Revert store"}
          </button>
          {onCheckLive && (
            <button type="button" className="btn quiet" onClick={onCheckLive} disabled={busy}>
              {checking ? "Checking…" : "Check checkout live"}
            </button>
          )}
          {hint && <p id="store-hint" className="store-hint">{hint}</p>}
        </div>
      </div>
    </section>
  );
}
