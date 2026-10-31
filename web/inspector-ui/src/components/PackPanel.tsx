import { checkVerdict, providerLabel, providerNote, type Invariant, type Readiness, type RepairScenario, type Tone } from "@/lib/faultline-api";
import type { Selection } from "@/components/ScenarioRail";

/** A registered sandbox repair: reproduce in isolation, propose, gate, and verify. */
export default function PackPanel(props: {
  scenario: RepairScenario; covering: Invariant[];
  readiness: Readiness | null; readinessError: string | null; gate: string | null;
  running: boolean; busy: boolean; submitting: boolean; cancelling: boolean; cancelRequested: boolean;
  onRun: (mode: "repair" | "detect") => void; onCancel: (() => void) | null; onRetry: () => void;
  onSelect: (s: Selection) => void;
}) {
  const { scenario, covering, readiness, readinessError, gate, running, busy, submitting, cancelling, cancelRequested, onRun, onCancel, onRetry, onSelect } = props;
  const status = readiness?.status;
  const note = readiness?.model ? providerNote(readiness.model.provider) : null;
  const sourceTone: Tone = !readiness?.model ? "idle" : readiness.model.provider === "meta" && readiness.model.available ? "idle" : "warn";
  // Project-runner scenarios are defined by a ReproSpec rather than one route.
  const project = scenario.executor === "repro";
  const [method, ...path] = scenario.route.split(" ");

  return (
    <article className="workspace" aria-labelledby="scenario-h">
      <p className="result-kicker">{project ? "Project sandbox scenario" : "Sandbox repair scenario"} <code className="muted">{scenario.id}</code></p>
      <h1 id="scenario-h">{scenario.title}</h1>
      {scenario.description && <p className="lede">{scenario.description.replace(/\.?$/, ".")}</p>}
      {scenario.route && <p className="request-line"><span className="method">{method}</span><code>{path.join(" ")}</code></p>}
      <dl className="facts">
        <div><dt>Repair scope</dt><dd>{scenario.target_file}</dd></div>
        {scenario.error_fingerprint && <div><dt>Server error</dt><dd>{scenario.error_fingerprint}</dd></div>}
        <div><dt>Checks</dt><dd>{project
          ? `${scenario.expected_assertions.length} ReproSpec assertions, rerun on the baseline twice and on every candidate`
          : `${scenario.expected_assertions.length} browser-journey checks, plus HTTP regressions on every candidate`}</dd></div>
      </dl>
      <div className="actions">
        <button type="button" className="btn primary run-button" onClick={() => onRun("repair")}
          disabled={status !== "ready" || running || busy} aria-describedby={gate ? "gate" : undefined}>
          {submitting ? "Starting…" : running ? "Repair in progress…" : "Run sandbox repair"}
        </button>
        {onCancel && <button type="button" className="btn" onClick={onCancel} disabled={busy || cancelRequested}>
          {cancelRequested || cancelling ? "Stopping…" : "Stop run"}
        </button>}
        {status === "detect_only" && !running && <button type="button" className="btn" onClick={() => onRun("detect")} disabled={busy}>Run detection only</button>}
      </div>
      <p className="source-line" data-tone={sourceTone}>
        <span className="source-key">Patch source</span>
        <span>{readiness ? providerLabel(readiness.model) : readinessError ? "Unknown until the orchestrator responds" : "Checking repair provider…"}</span>
        {note && <span className="source-note">{note}</span>}
      </p>
      {gate && <p id="gate" className="gate" role="status">{gate}</p>}
      {(readinessError || status === "blocked") && (
        <button type="button" className="btn quiet retry" onClick={onRetry} disabled={busy}>Check again</button>
      )}
      <p className="scope">
        {project
          ? "Each run starts the project from its tracked source in a fresh isolated runtime. Your working source is never changed; review the verified diff and apply it yourself."
          : "Each run starts from the pinned seed in a fresh isolated runtime, so the live store keeps its current source until you apply a fix from the bar above."}
      </p>
      {covering.length > 0 && (
        <section className="covering" aria-labelledby="covering-h">
          <h2 id="covering-h">{project ? "Live check of this scenario" : "Live checks on this route"}</h2>
          <ul className="rows">
            {covering.map((invariant) => {
              const verdict = invariant.latest_check ? checkVerdict(invariant.latest_check) : null;
              return (
                <li key={invariant.id}>
                  <button type="button" className="btn quiet" onClick={() => onSelect({ kind: "invariant", id: invariant.id })}>{invariant.title}</button>
                  <span data-tone={verdict?.tone ?? "idle"}>{verdict?.title ?? "Not checked yet"}</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </article>
  );
}
