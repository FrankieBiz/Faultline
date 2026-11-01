"use client";

import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { crawlInFlight, crawlSummary, plural, Seismograph, type CrawlState, type Seismic } from "@/components/CrawlerHud";
import { agentSnippets, crawlCompleted, DEFAULT_GATE_URL, gateErrorResult, gateResult, trailAction, type GateResult } from "@/lib/agent-gate";
import type { CrawlTelemetry } from "@/lib/faultline-api";

type Verdict = "idle" | "running" | "safe" | "blocked" | "inconclusive";

// Only a crawl that finished exploring clears the gate. A direct HTTP check is not a gate crawl, so
// even a passing one leaves the gate inconclusive, as `faultline gate` would be without its crawler.
const verdictOf = (state: CrawlState | null): Verdict =>
  !state ? "idle" : crawlInFlight(state) ? "running"
    : state.phase === "caught" ? "blocked"
    : state.phase === "clean" && state.source === "playwright" && crawlCompleted(state.telemetry) ? "safe" : "inconclusive";

const SEISMIC: Record<Verdict, Seismic> = { idle: "still", running: "hunt", safe: "resonance", blocked: "rupture", inconclusive: "still" };

/** Ends a crawler message with a period, so the next sentence does not run into it. */
const sentence = (text: string) => /[.!?…]$/.test(text.trim()) ? text.trim() : `${text.trim()}.`;

const portOf = (url: string, fallback: string) => {
  try {
    return new URL(url).port || fallback;
  } catch {
    return fallback;
  }
};

function CopyButton({ text, label, onCopied }: { text: string; label: string; onCopied: (message: string) => void }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      onCopied(`Copied ${label}`);
      setTimeout(() => setDone(false), 1600);
    } catch {
      onCopied("The clipboard is unavailable here. Select the text to copy it.");
    }
  };
  return (
    <button type="button" className="btn quiet gate-copy" data-done={done || undefined} onClick={copy} aria-label={`Copy ${label}`}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}

/**
 * What the gate can say without the crawler's final report (a direct HTTP check, or an engine that
 * predates telemetry): the run's own steps and defect, in the report's shape.
 */
function telemetryFromState(state: CrawlState): CrawlTelemetry {
  const { actions, trail } = crawlSummary(state);
  const d = state.defect;
  let origin = "";
  try {
    origin = new URL(state.target).origin;
  } catch {
    // An unparsable target keeps the bare path.
  }
  const pages = state.source === "check" ? [] : [...new Set(state.lines.filter((l) => l.kind !== "scan" && l.kind !== "session")
    .map((l) => l.kind === "visit" ? l.label : l.page).filter((p): p is string => Boolean(p)))];
  return {
    status: d ? "failure" : "clean", target_url: state.target, elements_explored: 0,
    screens_visited: pages.map((path) => ({ path })), actions_taken: actions,
    failure: !d ? null : d.status
      ? { kind: "http_error", method: d.method, url: origin + d.path, endpoint: d.path, status: d.status }
      : { kind: "request_failed", method: d.method, url: origin + d.path, endpoint: d.path, message: "no response" },
    reproduction_trail: trail.map((line, i) => `${i + 1}. ${trailAction(line)}`
      + (line.page && line.kind !== "visit" && line.kind !== "session" ? ` on ${line.page}` : "")
      + (!line.ok && d ? ` -> ${d.status ? `HTTP ${d.status}` : "no response"} on ${d.method} ${d.path}` : "")),
  };
}

/** The agent fix prompt, or the whole JSON verdict, exactly as `faultline gate --json` would return them. */
function Payload({ result, exact, onCopied }: { result: GateResult; exact: boolean; onCopied: (message: string) => void }) {
  const [view, setView] = useState<"prompt" | "json">("prompt");
  const text = view === "prompt" ? result.agent_remediation_prompt ?? "" : JSON.stringify(result, null, 2);
  return (
    <figure className="gate-payload">
      <figcaption>
        <span><span aria-hidden="true">🤖 </span>AI Agent Remediation Payload</span>
        <span className="gate-payload-tools">
          <span className="gate-views" role="group" aria-label="Payload format">
            <button type="button" aria-pressed={view === "prompt"} onClick={() => setView("prompt")}>Prompt</button>
            <button type="button" aria-pressed={view === "json"} onClick={() => setView("json")}>JSON</button>
          </span>
          <CopyButton text={text} label={view === "prompt" ? "the agent fix prompt" : "the JSON verdict"} onCopied={onCopied} />
        </span>
      </figcaption>
      <pre><code>{text}</code></pre>
      <p className="gate-payload-note">
        {exact ? <>The same <code>agent_remediation_prompt</code> and verdict that <code>faultline gate --json</code> returns for this run.</>
          : <>Built from this run in the <code>faultline gate --json</code> format.</>}{" "}
        {result.failure ? "Hand it to the coding agent, then fix the bug and run the gate again."
          : "Hand it to the coding agent: it says why the gate could not pass and what to do before deploying."}
      </p>
    </figure>
  );
}

/**
 * The Pre-Flight Agent Gate: the check a coding agent or CI pipeline runs before a deploy.
 * "Run Pre-Flight Gate" sends the same Playwright crawl as the hero, so every verdict, count,
 * and reproduction step here comes from that live run. Nothing is simulated. The verdict,
 * summary, and agent fix prompt follow `faultline gate --json` (lib/agent-gate.ts ports it).
 * The tabs wire `faultline gate` into agents and CI.
 */
export default function AgentGatePanel(props: {
  /** The crawl this panel launched, or null when the last crawl came from elsewhere. */
  state: CrawlState | null;
  storefrontUrl: string;
  /** The demo store's source state, which decides what its pill should expect. */
  storeState: "seeded" | "patched" | "modified" | "missing" | null;
  busy: boolean;
  onRun: (url: string) => Promise<void>;
  /** Whether the Mission HUD also shows this run; it offers the sandbox repair. */
  missionOpen: boolean;
  onOpenMission: () => void;
  onReset: () => void;
}) {
  const { state, storefrontUrl, storeState, busy, onRun } = props;
  const ids = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [copied, setCopied] = useState("");

  const verdict = verdictOf(state);
  const summary = state ? crawlSummary(state) : null;
  const defect = state?.defect ?? null;
  const crawler = state?.source !== "check";
  const snippetUrl = state?.target ?? DEFAULT_GATE_URL;
  const snippets = agentSnippets(snippetUrl);
  const snippet = snippets[tab];

  const presets = [
    {
      label: `Storefront (:${portOf(storefrontUrl, "3000")})`, value: storefrontUrl,
      // The demo store is clean only once the verified fix is applied; seeded, it fails checkout.
      expect: storeState === "patched" ? { tone: "ok", text: "Clean → Safe to Deploy" }
        : storeState === "seeded" ? { tone: "bad", text: "Seeded defect → Blocked" } : null,
    },
  ];

  /** Normalizes the typed URL, or shows why it cannot be used and returns null. */
  const target = (typed: string): string | null => {
    setError(null);
    const raw = typed.trim();
    if (!raw) {
      setError("Enter the preview URL your agent would deploy, such as http://localhost:3000/.");
      return null;
    }
    const value = /^[a-z][a-z\d+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`;
    try {
      if (!["http:", "https:"].includes(new URL(value).protocol)) throw new Error();
    } catch {
      setError("Enter a full http:// or https:// URL.");
      return null;
    }
    if (value !== raw) setUrl(value);
    return value;
  };

  const run = async (typed: string) => {
    const value = target(typed);
    if (!value) return;
    try {
      await onRun(value);
    } catch {
      setError("The gate could not start. Check that the FaultLine engine is running.");
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run(url);
  };

  const pick = (value: string) => {
    setUrl(value);
    void run(value);
  };

  // Arrow keys move between tabs, as in any tablist.
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const to = event.key === "Home" ? 0 : event.key === "End" ? snippets.length - 1 : (tab + step + snippets.length) % snippets.length;
    if (!step && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    setTab(to);
    tabRefs.current[to]?.focus();
  };

  // The crawler's final report is authoritative; fields it lacks come from the run's own lines.
  const exact = Boolean(state?.telemetry?.status);
  // A crawl that found nothing but stopped early has a report, and the CLI's own inconclusive verdict.
  const unfinished = verdict === "inconclusive" && state?.source === "playwright" && state.telemetry?.status === "clean";
  const result: GateResult | null = !state || verdict === "idle" || verdict === "running" ? null
    : unfinished ? gateResult({ ...telemetryFromState(state), ...state.telemetry }, state.target)
    : verdict === "inconclusive" ? gateErrorResult(
      state.source === "check" && state.phase === "clean"
        ? "The Playwright crawler did not run. A direct HTTP check passed, but one request is not a crawl of the preview."
        : state.note ?? "the crawl ended before it reported a result", state.target)
    : gateResult({ ...telemetryFromState(state), ...state.telemetry }, state.target);
  const elements = state?.telemetry?.elements_explored ?? null;

  return (
    <section id="gate" className="preflight shell" aria-labelledby={`${ids}-h`} data-verdict={verdict}>
      <div className="gate-frame">
        <Seismograph mode={SEISMIC[verdict]} />
        <header className="gate-head">
          <p className="gate-kicker"><span className="gate-lock" aria-hidden="true" />Pre-Flight Agent Gate · Claude Code · Codex · Cursor · Devin · CI</p>
          <h2 id={`${ids}-h`}>Nothing ships until the gate clears it.</h2>
          <p className="gate-lede">
            Before an AI agent or CI pipeline deploys, FaultLine crawls the preview with deterministic heuristics, within an action and time budget.{" "}
            <strong>Exit 1 blocks</strong> a defect, with the exact reproduction for the agent, or a crawl that did not finish.{" "}
            <strong>Exit 0</strong> means exploration finished clean: a smoke signal for the flows it reached, not proof of business logic.
          </p>
        </header>

        <div className="gate-grid">
          <div className="gate-sim">
            <form className="gate-form" onSubmit={submit} noValidate aria-label="Run the pre-flight gate" data-running={verdict === "running" || undefined}>
              <label className="gate-label" htmlFor={`${ids}-u`}>Target preview URL</label>
              <div className="gate-field">
                <span className="gate-prompt" aria-hidden="true">$ faultline gate</span>
                <input id={`${ids}-u`} type="url" inputMode="url" autoComplete="off" spellCheck={false}
                  placeholder={DEFAULT_GATE_URL} value={url} onChange={(e) => setUrl(e.target.value)}
                  aria-invalid={error ? true : undefined} aria-describedby={error ? `${ids}-e` : undefined} />
                <button type="submit" className="btn primary gate-run" disabled={busy}>
                  <span aria-hidden="true">🛡️ </span>{verdict === "running" ? "Gate scanning…" : "Run Pre-Flight Gate"}
                </button>
              </div>
              {error && <p id={`${ids}-e`} className="gate-error" role="alert">{error}</p>}
              <ul className="gate-pills" aria-label="One-click gate targets">
                {presets.map((preset) => (
                  <li key={preset.label}>
                    <button type="button" className="gate-pill" disabled={busy} aria-pressed={state?.target === preset.value}
                      onClick={() => pick(preset.value)}>
                      <span>{preset.label}</span>
                      {preset.expect && <span className="gate-expect" data-tone={preset.expect.tone}>{preset.expect.text}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </form>

            <div className="gate-verdict" aria-live="polite">
              {verdict === "idle" && (
                <p className="gate-await">
                  <span className="gate-await-mark" aria-hidden="true" />
                  Gate armed. Pick a target. A real headless Chromium crawl decides the verdict.
                </p>
              )}

              {verdict === "running" && state && summary && (
                <div className="gate-scan">
                  <p className="gate-scan-line"><span className="hud-dot" aria-hidden="true" />
                    {state.phase === "retrying" ? "Waking the crawler…" : state.phase === "fallback" ? "Crawler offline. Sending a direct HTTP check…" : `Scanning ${state.target}…`}
                  </p>
                  <p className="gate-scan-count">{plural(summary.actions, "action")} · {plural(summary.screens, "screen")}</p>
                  {summary.steps.at(-1) && <p className="gate-scan-step">{summary.steps.at(-1)!.text}</p>}
                </div>
              )}

              {verdict === "safe" && state && summary && (
                <div className="gate-result" data-tone="ok">
                  <p className="gate-badge" data-tone="ok"><span aria-hidden="true">✅ </span>Verdict: Safe to deploy</p>
                  <dl className="gate-stats">
                    {crawler ? <>
                      {elements !== null && <div><dt>Elements</dt><dd>{elements}</dd></div>}
                      <div><dt>Actions</dt><dd>{summary.actions}</dd></div>
                      <div><dt>Screens</dt><dd>{summary.screens}</dd></div>
                    </> : <div><dt>Requests</dt><dd>{summary.steps.length}</dd></div>}
                    <div data-tone="ok"><dt>Defects</dt><dd>0</dd></div>
                  </dl>
                  <p className="gate-confirm">
                    {exact && result ? result.summary : `Zero defects. Every action across ${plural(summary.screens, "screen")} completed without a failing request.`}{" "}
                    <code>faultline gate</code> exits 0: a smoke signal for the flows it explored, not proof the business logic is right.
                  </p>
                  <div className="gate-actions"><button type="button" className="btn quiet" onClick={props.onReset}>Clear</button></div>
                </div>
              )}

              {verdict === "blocked" && state && summary && defect && (
                <div className="gate-result" data-tone="bad">
                  <p className="gate-badge" data-tone="bad"><span aria-hidden="true">🛡️ </span>Verdict: Deployment blocked</p>
                  <p className="gate-intercept">Defect intercepted before going live</p>
                  <p className="gate-defect">
                    <span className="hud-code">{defect.status ? `HTTP ${defect.status}` : "No response"}</span>
                    <span className="sr-only"> on </span><span>{defect.method} {defect.path}</span>
                  </p>
                  <ol className="gate-trail" aria-label="Reproduction trail">
                    {summary.trail.map((line, i) => (
                      <li key={i} data-ok={line.ok}>
                        <span className="gate-trail-n" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                        <span>{trailAction(line, (text) => `“${text}”`)}
                          {line.page && line.kind !== "visit" && <span className="muted"> on {line.page}</span>}
                          {!line.ok && <strong> → {defect.status ? `HTTP ${defect.status}` : "failed"} on {defect.method} {defect.path}</strong>}
                        </span>
                      </li>
                    ))}
                  </ol>
                  {result && <Payload key={state.startedAt} result={result} exact={exact} onCopied={setCopied} />}
                  <div className="gate-actions">
                    {!props.missionOpen && (
                      <button type="button" className="btn gate-mission" onClick={props.onOpenMission}>
                        <span aria-hidden="true">🛠️ </span>Open in Mission HUD to repair
                      </button>
                    )}
                    <button type="button" className="btn quiet" onClick={props.onReset}>Clear</button>
                  </div>
                </div>
              )}

              {verdict === "inconclusive" && state && (
                <div className="gate-result" data-tone="warn">
                  <p className="gate-badge" data-tone="warn"><span aria-hidden="true">🛡️ </span>Verdict: Inconclusive · deployment blocked</p>
                  {unfinished && summary && (
                    <dl className="gate-stats">
                      {elements !== null && <div><dt>Elements</dt><dd>{elements}</dd></div>}
                      <div><dt>Actions</dt><dd>{summary.actions}</dd></div>
                      <div><dt>Screens</dt><dd>{summary.screens}</dd></div>
                      <div data-tone="warn"><dt>Stopped by</dt><dd>{result?.stop_reason ?? "unknown"}</dd></div>
                    </dl>
                  )}
                  <p className="gate-confirm">
                    {unfinished && result ? <>No defect in the flows it explored, but exploration did not finish, so this is not a pass. {result.summary}</>
                      : <>The gate could not finish, so it fails closed. {sentence(result?.error?.message ?? state.note ?? "The crawl ended before it reported a result.")}</>}{" "}
                    <code>faultline gate</code> exits 1 here too.
                  </p>
                  {result && <Payload key={state.startedAt} result={result} exact={unfinished && exact} onCopied={setCopied} />}
                  <div className="gate-actions"><button type="button" className="btn quiet" onClick={props.onReset}>Clear</button></div>
                </div>
              )}
            </div>
          </div>

          <div className="gate-connect">
            <h3 className="gate-connect-h">Connect your agents</h3>
            <div className="gate-tabs" role="tablist" aria-label="Integrations">
              {snippets.map((s, i) => (
                <button key={s.id} ref={(node) => { tabRefs.current[i] = node; }} type="button" role="tab" id={`${ids}-t-${s.id}`}
                  aria-selected={i === tab} aria-controls={`${ids}-p`} tabIndex={i === tab ? 0 : -1}
                  className="gate-tab" onClick={() => setTab(i)} onKeyDown={onTabKey}>
                  {s.tab}
                </button>
              ))}
            </div>
            <div className="gate-panel" role="tabpanel" id={`${ids}-p`} aria-labelledby={`${ids}-t-${snippet.id}`}>
              <div className="gate-file">
                <code>{snippet.file}</code>
                <CopyButton text={snippet.body} label={snippet.tab} onCopied={setCopied} />
              </div>
              <pre className="gate-code"><code>{snippet.body}</code></pre>
              <p className="gate-note">{snippet.note}</p>
            </div>
          </div>
        </div>
        <p className="sr-only" role="status" aria-live="polite">{copied}</p>
      </div>
    </section>
  );
}
