import { checkVerdict, type Invariant, type ScenarioListing, type Tone } from "@/lib/faultline-api";

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

function lastCheck(invariant: Invariant): RailStatus {
  if (!invariant.latest_check) return { tone: "idle", text: "not checked yet" };
  const verdict = checkVerdict(invariant.latest_check);
  return { tone: verdict.tone, text: `last check: ${verdict.title.toLowerCase()}` };
}

/** A rail status: an evidence tone, or "active" while a live check or sandbox run is in flight. */
export type RailStatus = { tone: Tone | "active"; text: string };

function Group(props: {
  title: string; kind: string; empty: string; selection: Selection | null; onSelect: (s: Selection) => void;
  items: ({ kind: Selection["kind"]; id: string; title: string; route: string } & RailStatus)[];
}) {
  const { title, kind, empty, items, selection, onSelect } = props;
  return (
    <section className="rail-group" aria-label={title}>
      <h2><span>{title}</span><span className="rail-kind" aria-hidden="true">{kind}{items.length > 0 && ` · ${items.length}`}</span></h2>
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
                  <span className="rail-status" data-tone={item.tone}><span className="sr-only">, </span>{item.text}</span>
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
  /** Sandbox state per repair scenario, from the run on screen; scenarios without one are idle. */
  packStatus: Record<string, RailStatus>;
  /** The invariant whose live check is in flight. */
  checkingId: string | null;
  onSelect: (s: Selection) => void; onNew: () => void; onRetry: () => void;
}) {
  const { listing, error, selection, packStatus, checkingId, onSelect, onNew, onRetry } = props;
  const rules = listing?.invariants.filter((i) => i.source !== "probe") ?? [];
  const probes = listing?.invariants.filter((i) => i.source === "probe") ?? [];
  const entry = (i: Invariant) => {
    const requests = i.repro?.steps.filter((step) => step.action === "request").length ?? 1;
    const route = `${requestLabel(i)}${requests > 1 ? `, ${requests} requests` : ""}`;
    const status: RailStatus = i.id === checkingId ? { tone: "active", text: "checking live…" }
      : i.live_note ? { tone: "idle", text: "sandbox only" } : lastCheck(i);
    return { kind: "invariant" as const, id: i.id, title: i.title, route, ...status };
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
          <Group title="Sandbox repair" kind="sandbox" empty="No repair scenarios are registered." selection={selection} onSelect={onSelect}
            items={listing.scenarios.map((s) => ({
              kind: "pack", id: s.id, title: s.title, route: s.route || `ReproSpec, ${s.expected_assertions.length} assertions`,
              ...(packStatus[s.id] ?? { tone: "idle", text: "repairable in the sandbox" }),
            }))} />
          <Group title="faultline.toml" kind="http" empty={listing.project.config_path ? "No [scenarios] or [[invariants.rule]] entries yet." : "No faultline.toml found. Run faultline init."}
            selection={selection} onSelect={onSelect} items={rules.map(entry)} />
          {listing.project.errors.map((message) => <p key={message} className="rail-warning">{message}</p>)}
          <Group title="Added here" kind="http" empty="Probe any URL with New invariant. It is saved and listed here." selection={selection} onSelect={onSelect}
            items={probes.map(entry)} />
        </>
      )}
    </nav>
  );
}
