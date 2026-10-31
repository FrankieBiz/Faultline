"use client";

import { useState } from "react";
import { requestLabel } from "@/components/ScenarioRail";
import { checkVerdict, type BodyCheck, type CheckRecord, type Invariant, type ReproStepWire, type SessionResult } from "@/lib/faultline-api";

const clock = (iso: string) => new Date(iso).toLocaleString([], { hour12: false });

function expectation(check: BodyCheck): string {
  const path = check.path ?? "$";
  if ("equals" in check) return `${path} equals ${JSON.stringify(check.equals)}`;
  if (check.equals_path) return `${path} equals ${check.equals_path}`;
  if (check.matches) return `${path} matches /${check.matches}/`;
  if (check.type) return `${path} is ${check.type === "integer" || check.type === "array" || check.type === "object" ? "an" : "a"} ${check.type}`;
  return `${path} ${check.exists ? "exists" : "is absent"}`;
}

const KICKER: Record<Invariant["source"], string> = {
  config: "Rule from faultline.toml", scenario: "Scenario from faultline.toml", probe: "Probe added here",
};

function stepExpectation(step: ReproStepWire): string {
  const check = step.check ?? {};
  return typeof check.status === "number" ? `HTTP status ${check.status}` : expectation(check);
}

function Session({ session, index, sources }: { session: SessionResult; index: number; sources: Map<string, string> }) {
  const failed = session.assertions.filter((a) => !a.passed).length;
  const failing = new Set(session.assertions.filter((a) => !a.passed).map((a) => sources.get(a.id)));
  const tone = session.error ? "warn" : failed ? "bad" : "ok";
  return (
    <figure className="session" data-tone={tone}>
      <figcaption className="eyebrow">Session {index + 1} <span title={session.session_id}>{session.session_id.slice(0, 8)}</span></figcaption>
      <p className="session-status">{session.status ?? "No response"}</p>
      <p className="signal muted">
        {session.error ? `Request failed: ${session.error}` : `${session.duration_ms ?? "?"} ms${session.content_type ? `, ${session.content_type.split(";")[0]}` : ""}`}
      </p>
      {session.requests.length > 1 && (
        <ul className="request-rows" aria-label={`Session ${index + 1} requests`}>
          {session.requests.map((r) => (
            <li key={r.step_id}>
              <code><span className="muted">{r.step_id}</span> {r.method} {r.path}</code>
              <span data-tone={failing.has(r.step_id) ? "bad" : "ok"}>{r.status}</span>
            </li>
          ))}
        </ul>
      )}
      {session.assertions.length > 0 && (
        <ul className="asserts" aria-label={`Session ${index + 1} expectations`}>
          {session.assertions.map((a) => (
            <li key={a.id} data-tone={a.passed ? "ok" : "bad"}>
              <span aria-hidden="true">{a.passed ? "✓" : "✕"}</span>
              <span className="sr-only">{a.passed ? "Passed:" : "Failed:"}</span>
              <span>{a.label}</span>
              {!a.passed && <span className="muted">expected {a.expected}, observed {a.observed}</span>}
            </li>
          ))}
        </ul>
      )}
      {session.fingerprint && <p className="signal">Server error: {session.fingerprint}</p>}
      {session.excerpt !== null && session.excerpt !== "" && (
        <details className="excerpt">
          <summary>Response body{session.truncated ? ", first 600 characters" : ""}</summary>
          <pre className="code" tabIndex={0}><span>{session.excerpt}</span></pre>
        </details>
      )}
    </figure>
  );
}

function CheckResult(props: {
  check: CheckRecord; sources: Map<string, string>; stale: boolean;
  canRepair: boolean; repairGate: string | null; repairing: boolean; onRepair: (id: string) => void;
}) {
  const { check, sources, stale, canRepair, repairGate, repairing, onRepair } = props;
  const verdict = checkVerdict(check);
  return (
    <section className="check" data-tone={verdict.tone} aria-labelledby="check-h" aria-busy={stale}>
      <p className="result-kicker">Live check, {clock(check.created_at)}</p>
      <h2 id="check-h" aria-live="polite">{verdict.title}</h2>
      <p className="lede">{verdict.detail}</p>
      <p className="check-target"><code>{check.method} {check.url}</code></p>
      <div className="sessions">
        {check.sessions.map((session, i) => <Session key={session.session_id || i} session={session} index={i} sources={sources} />)}
      </div>
      {check.repair ? (
        <div className="repair-callout">
          <div>
            <p className="repair-title">Repairable in the sandbox: {check.repair.title}</p>
            <p className="muted">{check.repair_note} The patch may touch only <code>{check.repair.target_file}</code>.</p>
            {repairGate && <p className="gate">{repairGate}</p>}
          </div>
          <button type="button" className="btn primary" disabled={!canRepair || stale} onClick={() => onRepair(check.repair!.scenario_id)}>
            {repairing ? "Starting…" : "Repair in sandbox"}
          </button>
        </div>
      ) : check.repair_note ? <p className="repair-note">{check.repair_note}</p> : null}
    </section>
  );
}

/** One live HTTP invariant: what it sends, what it expects, and every recorded check. */
export default function InvariantPanel(props: {
  invariant: Invariant; checks: CheckRecord[] | undefined; checksError: string | null;
  checking: boolean; busy: boolean; canRepair: boolean; repairGate: string | null; repairing: boolean;
  onCheck: (port: number | null) => void; onRepair: (scenarioId: string) => void; onRemove: () => void;
}) {
  const { invariant, checks, checksError, checking, busy, canRepair, repairGate, repairing, onCheck, onRepair, onRemove } = props;
  const [port, setPort] = useState(invariant.default_port ? String(invariant.default_port) : "");
  const usesPort = invariant.url.includes("{port}");
  const portValue = Number(port);
  const portValid = !usesPort || (Number.isInteger(portValue) && portValue >= 1 && portValue <= 65535);
  const latest = checks?.[0] ?? invariant.latest_check ?? null;
  const earlier = (checks ?? []).slice(1);
  const steps = invariant.repro?.steps ?? null;
  const requests = steps?.filter((step) => step.action === "request") ?? [];
  const asserts = steps?.filter((step) => step.action === "assert") ?? [];
  // Which request each expectation reads; single-request checks all read "request".
  const sources = new Map(steps ? asserts.map((step) => [step.id, step.source ?? ""]) : [["status", "request"]]);
  const origin = requests[0]?.path && invariant.url.endsWith(requests[0].path)
    ? invariant.url.slice(0, invariant.url.length - requests[0].path.length) : invariant.url;
  const expectations = steps
    ? [`${asserts.length} ${asserts.length === 1 ? "assertion" : "assertions"} across ${requests.length} ${requests.length === 1 ? "request" : "requests"}`]
    : [
      ...(invariant.expected_status !== null ? [`HTTP status ${invariant.expected_status}`] : []),
      ...invariant.assertions.map(expectation),
    ];

  return (
    <article className="workspace" aria-labelledby="scenario-h">
      <p className="result-kicker">{KICKER[invariant.source]} <code className="muted">{invariant.id}</code></p>
      <h1 id="scenario-h">{invariant.title}</h1>
      {invariant.description && invariant.description !== invariant.title && <p className="lede">{invariant.description}</p>}
      {steps ? (
        <ol className="request-list" aria-label="Requests in this ReproSpec">
          {requests.map((step) => (
            <li key={step.id} className="request-line"><span className="method">{step.method ?? "GET"}</span><code>{origin}{step.path}</code><span className="muted step-id">{step.id}</span></li>
          ))}
        </ol>
      ) : (
        <p className="request-line"><span className="method">{invariant.method}</span><code>{invariant.url}</code></p>
      )}
      <dl className="facts">
        <div><dt>Expects</dt><dd>{expectations.join("; ")}</dd></div>
        {invariant.fingerprint && <div><dt>Fingerprint</dt><dd>{invariant.fingerprint}</dd></div>}
        <div><dt>Route</dt><dd>{requestLabel({ ...invariant, source: "config" })}</dd></div>
      </dl>
      {invariant.has_body && (
        <details className="excerpt">
          <summary>Request body</summary>
          <pre className="code" tabIndex={0}><span>{JSON.stringify(invariant.body, null, 2)}</span></pre>
        </details>
      )}
      {steps && (
        <details className="excerpt">
          <summary>Expectations · {asserts.length}</summary>
          <ul className="asserts">
            {asserts.map((step) => <li key={step.id}><code>{step.id}</code><span className="muted">{stepExpectation(step)}</span></li>)}
          </ul>
        </details>
      )}
      <form className="actions" onSubmit={(e) => { e.preventDefault(); onCheck(usesPort ? portValue : null); }}>
        {usesPort && (
          <label className="field port-field">
            <span>Service port</span>
            <input type="number" inputMode="numeric" min={1} max={65535} required value={port} onChange={(e) => setPort(e.target.value)} />
          </label>
        )}
        <button type="submit" className="btn primary run-button" disabled={busy || !portValid || invariant.live_note !== null}>{checking ? "Checking live…" : "Run live check"}</button>
        {invariant.source === "probe" && (
          <button type="button" className="btn quiet" onClick={onRemove} disabled={busy}>Remove probe</button>
        )}
        {checking && <p className="scan" role="status"><span className="scan-bar" aria-hidden="true" />Sending the request from two fresh sessions…</p>}
      </form>
      {invariant.live_note && (
        <p className="gate">{invariant.live_note} Run it in the sandbox with <code>faultline run {invariant.id.replace(/^scenario\./, "")}</code>.</p>
      )}
      {checksError && <p className="notice" role="status">{checksError}</p>}
      {latest ? (
        <CheckResult check={latest} sources={sources} stale={checking} canRepair={canRepair} repairGate={repairGate} repairing={repairing} onRepair={onRepair} />
      ) : (
        <p className="empty">Not checked yet. Run a live check to send the request from two fresh sessions.</p>
      )}
      {earlier.length > 0 && (
        <details className="history">
          <summary>Earlier checks · {earlier.length}</summary>
          <ul className="rows">
            {earlier.map((check) => {
              const verdict = checkVerdict(check);
              return (
                <li key={check.id}>
                  <time dateTime={check.created_at}>{clock(check.created_at)}</time>
                  <span data-tone={verdict.tone}>{verdict.title}</span>
                  <span className="muted">{check.sessions.map((s) => s.status ?? s.error ?? "no response").join(", ")}</span>
                  <code className="muted">{check.url}</code>
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </article>
  );
}
