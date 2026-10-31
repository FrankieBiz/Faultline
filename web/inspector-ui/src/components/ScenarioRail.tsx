import { checkVerdict, type Invariant, type ScenarioListing } from "@/lib/faultline-api";

export type Selection = { kind: "pack" | "invariant"; id: string };

/** "GET /healthz", or host and path for a probe that names its own origin. */
export function requestLabel(invariant: Pick<Invariant, "method" | "url" | "source">): string {
  try {
    const url = new URL(invariant.url.replaceAll("{port}", "1"));
    const path = `${url.pathname}${url.search}`;
    return `${invariant.method} ${invariant.source === "probe" ? `${url.host}${path}` : path}`;
  } catch {
    return `${invariant.method} ${invariant.url}`;
  }
}

function lastCheck(invariant: Invariant) {
  if (!invariant.latest_check) return { tone: "idle" as const, text: "not checked yet" };
  const verdict = checkVerdict(invariant.latest_check);
  return { tone: verdict.tone, text: `last check: ${verdict.title.toLowerCase()}` };
}

function Group(props: {
  title: string; note?: string; empty: string; selection: Selection | null; onSelect: (s: Selection) => void;
  items: { kind: Selection["kind"]; id: string; title: string; route: string; tone: string; status: string }[];
}) {
  const { title, note, empty, items, selection, onSelect } = props;
  return (
    <section className="rail-group" aria-label={title}>
      <h2>{title}{note && <span className="muted"> {note}</span>}</h2>
      {items.length === 0 ? <p className="rail-empty">{empty}</p> : (
        <ul>
          {items.map((item) => {
            const selected = selection?.kind === item.kind && selection.id === item.id;
            return (
              <li key={`${item.kind}:${item.id}`}>
                <button type="button" className="rail-item" aria-current={selected ? "true" : undefined}
                  onClick={() => onSelect({ kind: item.kind, id: item.id })}>
                  <span className="rail-dot" data-tone={item.tone} aria-hidden="true" />
                  <span className="rail-name">{item.title}</span>
                  <span className="rail-route">{item.route}</span>
                  <span className="sr-only">, {item.status}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** Every scenario the controller knows: sandbox repairs, faultline.toml rules, and added probes. */
export default function ScenarioRail(props: {
  listing: ScenarioListing | null; error: string | null; selection: Selection | null;
  onSelect: (s: Selection) => void; onNew: () => void; onRetry: () => void;
}) {
  const { listing, error, selection, onSelect, onNew, onRetry } = props;
  const rules = listing?.invariants.filter((i) => i.source !== "probe") ?? [];
  const probes = listing?.invariants.filter((i) => i.source === "probe") ?? [];
  const entry = (i: Invariant) => {
    const check = lastCheck(i);
    const requests = i.repro?.steps.filter((step) => step.action === "request").length ?? 1;
    const route = `${requestLabel(i)}${requests > 1 ? `, ${requests} requests` : ""}`;
    return { kind: "invariant" as const, id: i.id, title: i.title, route, tone: check.tone, status: i.live_note ? "sandbox only" : check.text };
  };
  return (
    <nav className="rail" aria-label="Scenarios">
      <div className="rail-head">
        <p className="rail-project">
          {listing?.project.name ?? "Scenarios"}
          {listing?.project.config_path && <span className="muted"> from {listing.project.config_path}</span>}
        </p>
        <button type="button" className="btn primary rail-new" onClick={onNew}>New invariant</button>
      </div>
      {error && !listing && (
        <p className="rail-error" role="status">{error} <button type="button" className="btn quiet inline-btn" onClick={onRetry}>Check again</button></p>
      )}
      {listing && (
        <>
          <Group title="Sandbox repair" empty="No repair scenarios are registered." selection={selection} onSelect={onSelect}
            items={listing.scenarios.map((s) => ({ kind: "pack", id: s.id, title: s.title, route: s.route || `ReproSpec, ${s.expected_assertions.length} assertions`, tone: "idle", status: "repairable in the sandbox" }))} />
          <Group title="faultline.toml" empty={listing.project.config_path ? "No [scenarios] or [[invariants.rule]] entries yet." : "No faultline.toml found. Run faultline init."}
            selection={selection} onSelect={onSelect} items={rules.map(entry)} />
          {listing.project.errors.map((message) => <p key={message} className="rail-warning">{message}</p>)}
          <Group title="Added here" empty="Probe any URL with New invariant. It is saved and listed here." selection={selection} onSelect={onSelect}
            items={probes.map(entry)} />
        </>
      )}
    </nav>
  );
}
