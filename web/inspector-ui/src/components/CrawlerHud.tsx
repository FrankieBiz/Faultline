"use client";

import { useEffect, useRef, useState } from "react";
import { crawlCompleted, stopReasonOf } from "@/lib/agent-gate";
import type { CheckRecord, CrawlEvent, CrawlTelemetry, Tone } from "@/lib/faultline-api";
import { checkVerdict } from "@/lib/faultline-api";
import { CtaIcon } from "@/components/CtaIcon";

type Defect = Extract<CrawlEvent, { type: "defect" }>;

/**
 * One ticker line. `n` is the crawler's step number (a run of field fills on one page folds
 * into one line, `n` to `last`); the DOM scan has none. `label` is what the click trail shows.
 */
export interface CrawlLine {
  n: number | null; last?: number;
  kind: "visit" | "scan" | "click" | "fill" | "submit" | "session";
  text: string; label: string; page: string | null; ok: boolean;
  /** Set on the step that failed: the defect it caught, in a few words. */
  caught?: string;
}

/**
 * A chaos crawl as the HUD shows it. `source` says where every line came from: the Playwright
 * crawler's own events, or, when the crawler endpoint is not answering, the sessions of a
 * direct HTTP check sent in its place. Nothing here is inferred from clicks.
 */
export interface CrawlState {
  target: string;
  /** When the agent was launched (ms since the epoch); the mission clock starts here. */
  startedAt: number;
  phase: "connecting" | "retrying" | "running" | "fallback" | "caught" | "clean" | "incomplete" | "failed";
  source: "playwright" | "check";
  scan: { buttons: number; forms: number; links: number } | null;
  /** The crawler's final report summary, from its `done` event; null before then or for a direct check. */
  telemetry: CrawlTelemetry | null;
  lines: CrawlLine[];
  defect: (Omit<Defect, "type" | "trigger"> & { trigger: { kind: string; label: string; page: string | null } }) | null;
  /** Why a direct check stood in for the crawler; kept for as long as its result is shown. */
  fallbackReason: string | null;
  /** Retry progress or the final verdict, in one line. */
  note: string | null;
}

/** The sandbox repair started for the defect on screen, summarized from that run's evidence. */
export interface MissionRepair {
  running: boolean;
  /** The current pipeline step while running, e.g. "Verify the candidate". */
  stage: string | null;
  verified: boolean;
  /** Passing and total assertions of the verified candidate. */
  checks: { passed: number; total: number } | null;
  /** Where the candidate was verified, e.g. "the Bubblewrap sandbox under cgroup v2 limits". */
  sandbox: string;
  /** The settled outcome of an unverified run. */
  outcome: { tone: Tone; title: string } | null;
  /** Whether the verified fix can be written to the store's source now. */
  canApply: boolean;
  /** Why a verified fix has no apply step, or null. */
  applyNote: string | null;
  applying: boolean;
  /** Set once the store's source holds this run's fix; `live` is the latest live checkout, if any. */
  applied: { file: string; live: { tone: Tone; text: string } | null } | null;
}

export const crawlInFlight = (state: CrawlState | null) =>
  state !== null && ["connecting", "retrying", "running", "fallback"].includes(state.phase);

export const startCrawl = (target: string): CrawlState =>
  ({ target, startedAt: Date.now(), phase: "connecting", source: "playwright", scan: null, telemetry: null, lines: [], defect: null, fallbackReason: null, note: null });

export const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
const pathOf = (url: string) => {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
};

const STOPPED_BY: Record<string, string> = {
  max_actions: "its action budget",
  timeout: "its time limit",
  screen_limit: "its screen limit",
  skipped_commit_controls: "commit controls it may not click on this origin",
};

/** Why a crawl that found nothing is still not a clean result. */
function incompleteNote(telemetry: CrawlTelemetry | null): string {
  const reason = stopReasonOf(telemetry);
  const actions = telemetry?.actions_taken;
  const stopped = !telemetry ? "The engine did not report how the crawl ended"
    : reason ? `The crawl stopped at ${STOPPED_BY[reason] ?? `"${reason}"`}${typeof actions === "number" ? ` after ${plural(actions, "action")}` : ""}`
    : "The crawler did not report whether it finished exploring";
  return `No defect in the flows it explored, but this is inconclusive, not clean. ${stopped}, so unexplored flows remain. faultline gate blocks a run like this (incomplete_crawl).`;
}

/** Folds one crawler event into the HUD state. */
export function applyCrawlEvent(state: CrawlState, event: CrawlEvent): CrawlState {
  const next: CrawlState = { ...state, phase: state.phase === "connecting" || state.phase === "retrying" ? "running" : state.phase, note: null };
  switch (event.type) {
    case "scan": {
      const elements = event.buttons + event.links;
      const text = `Discovered ${plural(elements, "interactive element")} (${plural(event.buttons, "button")}, ${plural(event.links, "link")}) and ${plural(event.forms, "form")}`;
      return { ...next, scan: { buttons: event.buttons, forms: event.forms, links: event.links },
        lines: [...next.lines, { n: null, kind: "scan", text, label: "", page: null, ok: true }] };
    }
    case "step": {
      const caught = event.ok ? undefined : event.note ?? "failed";
      if (event.action === "visit") {
        return { ...next, lines: [...next.lines, { n: event.n, kind: "visit", text: `Navigating to ${event.target}…`, label: event.page ?? pathOf(event.target), page: null, ok: event.ok, caught }] };
      }
      const previous = next.lines.at(-1);
      // Consecutive field fills on one page read as one line: "Filled form fields (Name, Email, Address)".
      if (event.action === "fill" && event.ok && previous?.kind === "fill" && previous.ok && previous.page === event.page) {
        const fields = [...previous.label.split(", "), event.target];
        const merged: CrawlLine = { ...previous, last: event.n, label: fields.join(", "), text: `Filled form fields (${fields.join(", ")})` };
        return { ...next, lines: [...next.lines.slice(0, -1), merged] };
      }
      const text = event.action === "fill" ? `Filled "${event.target}"` : `Clicked "${event.target}"`;
      return { ...next, lines: [...next.lines, { n: event.n, kind: event.action, text, label: event.target, page: event.page, ok: event.ok, caught }] };
    }
    case "defect": {
      // The failing step names the endpoint it broke once the crawler reports it.
      const at = next.lines.findLastIndex((line) => !line.ok);
      const caught = `${event.status ? `HTTP ${event.status}` : event.method} on ${event.method} ${event.path}`;
      const lines = at < 0 ? next.lines : next.lines.map((line, i) => i === at ? { ...line, caught } : line);
      return { ...next, phase: "caught", lines, defect: { ...event } };
    }
    case "done": {
      const telemetry = event.telemetry ?? null;
      if (next.defect) return { ...next, phase: "caught", telemetry };
      // Clean only when exploration finished; a budget or deadline stop found nothing in what it covered.
      return crawlCompleted(telemetry) ? { ...next, phase: "clean", telemetry }
        : { ...next, phase: "incomplete", telemetry, note: incompleteNote(telemetry) };
    }
    case "error":
      return { ...next, phase: "failed", note: event.message };
  }
}

/** Replaces the ticker with the sessions of the direct check that stood in for the crawler. */
export function crawlFromCheck(state: CrawlState, record: CheckRecord, title: string): CrawlState {
  let n = 0;
  const lines = record.sessions.flatMap((session, i): CrawlLine[] => session.requests.length
    ? session.requests.map((r) => ({ n: ++n, kind: "session", text: `Session ${i + 1}: ${r.method} ${r.path} → HTTP ${r.status}`, label: `${r.method} ${r.path}`, page: null, ok: r.status < 400 }))
    : [{ n: ++n, kind: "session", text: `Session ${i + 1}: ${record.method} ${new URL(record.url).pathname} → ${session.status ? `HTTP ${session.status}` : `no response${session.error ? ` (${session.error})` : ""}`}`, label: `${record.method} ${new URL(record.url).pathname}`, page: null, ok: session.status !== null && session.status < 400 }]);
  const verdict = checkVerdict(record);
  const status = record.sessions.find((s) => s.status !== null)?.status ?? null;
  const defect = verdict.tone === "bad" ? {
    method: record.method, path: new URL(record.url).pathname, status,
    trigger: { kind: "Check", label: title, page: null },
    fingerprint: record.sessions.find((s) => s.fingerprint)?.fingerprint ?? null,
    scenario_id: record.repair?.scenario_id ?? null,
  } : null;
  return { ...state, source: "check", lines, defect, phase: defect ? "caught" : "clean", note: defect ? null : `${verdict.title}: ${verdict.detail}` };
}

const PHASE_LABEL: Record<CrawlState["phase"], string> = {
  connecting: "Launching", retrying: "Waking crawler", running: "Hunting", fallback: "Direct check",
  caught: "Defect caught", clean: "Clean", incomplete: "Inconclusive", failed: "Stopped",
};
const PHASE_TONE: Record<CrawlState["phase"], Tone | "active"> = {
  connecting: "active", retrying: "active", running: "active", fallback: "active",
  caught: "bad", clean: "ok", incomplete: "warn", failed: "warn",
};

/** What a crawl covered, counted from its ticker lines, and its click trail up to the failing step. */
export function crawlSummary(state: CrawlState) {
  const steps = state.lines.filter((line) => line.kind !== "scan");
  const actions = steps.filter((line) => line.kind !== "visit" && line.kind !== "session")
    .reduce((count, line) => count + (line.last !== undefined && line.n !== null ? line.last - line.n + 1 : 1), 0);
  const screens = new Set(steps.filter((line) => line.kind !== "session").map((line) => line.kind === "visit" ? line.label : line.page)).size;
  const trail = steps.slice(0, (steps.findLastIndex((line) => !line.ok) + 1) || steps.length);
  return { steps, actions, screens, trail };
}

/** The agent's status once a repair takes over from the hunt. */
function missionStatus(state: CrawlState, repair: MissionRepair | null): { label: string; tone: Tone | "active" } {
  if (repair?.applied) return { label: "Fix applied", tone: "ok" };
  if (repair?.applying) return { label: "Applying fix", tone: "active" };
  if (repair?.verified) return { label: "Fix verified", tone: "ok" };
  if (repair?.running) return { label: "Repairing", tone: "active" };
  if (repair?.outcome) return { label: "Repair not verified", tone: repair.outcome.tone };
  return { label: PHASE_LABEL[state.phase], tone: PHASE_TONE[state.phase] };
}

export type Seismic = "hunt" | "rupture" | "resonance" | "still";
const SEISMIC: Record<Tone | "active", Seismic> = { active: "hunt", bad: "rupture", ok: "resonance", warn: "still", idle: "still" };

/**
 * The seismograph traces, drawn at pixel scale: one 200 px tile per trace, repeated wide enough
 * for the widest frame, and scrolled left by exactly one tile so the loop is seamless. Offsets
 * are rounded before they are differenced, so every tile returns exactly to the baseline.
 */
const TILE = 200;
const bump = (x: number, at: number, width: number) => Math.exp(-(((x - at) / width) ** 2));
const spikes = (() => {
  let seed = 7;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  return Array.from({ length: TILE / 5 + 1 }, (_, i) => i === 0 || i === TILE / 5 ? 0 : (random() * 2 - 1) * (i % 6 === 3 ? 17 : 10));
})();
function trace(offset: (x: number) => number, step: number) {
  const ys = Array.from({ length: TILE / step + 1 }, (_, i) => Math.round(offset(i * step) * 10) / 10);
  const tile = ys.slice(1).map((y, i) => `l${step} ${+(y - ys[i]).toFixed(1)}`).join("");
  return `M0 ${20 + ys[0]}${tile.repeat(14)}`;
}
const TRACES: Record<Seismic, string> = {
  // A steady heartbeat while the agent hunts.
  hunt: trace((x) => -2.5 * bump(x, 62, 7) - 13 * bump(x, 100, 2.2) + 8 * bump(x, 106, 2.4) - 3.5 * bump(x, 140, 9), 1),
  // Jagged ruptures once a request fails.
  rupture: trace((x) => spikes[x / 5], 5),
  // A calm resonance once the fix is verified or nothing was broken.
  resonance: trace((x) => 3.5 * Math.sin((2 * Math.PI * x) / 100), 2),
  still: trace(() => 0, TILE),
};

/** A live waveform of the mission: decorative, since the status line says the same in words. */
export function Seismograph({ mode }: { mode: Seismic }) {
  return (
    <div className="seis" data-mode={mode} aria-hidden="true">
      <svg key={mode} className="seis-trace" width={TILE * 14} height={40} viewBox={`0 0 ${TILE * 14} 40`}>
        <path className="seis-glow" d={TRACES[mode]} />
        <path className="seis-line" d={TRACES[mode]} pathLength={1} />
      </svg>
    </div>
  );
}

const clockText = (ms: number) => {
  const tenths = Math.floor(ms / 100);
  return `${String(Math.floor(tenths / 600)).padStart(2, "0")}:${String(Math.floor((tenths % 600) / 10)).padStart(2, "0")}.${tenths % 10}s`;
};

/**
 * The mission clock: time the agent spent working, from launch through the crawl and then the
 * sandbox repair and apply. It pauses while the mission waits on a person, so it measures the agent.
 */
function MissionClock({ active, origin }: { active: boolean; origin: number }) {
  const [clock, setClock] = useState({ spent: 0, since: origin as number | null, now: origin });
  useEffect(() => {
    if (!active) {
      setClock((c) => c.since === null ? c : { spent: c.spent + Date.now() - c.since, since: null, now: Date.now() });
      return;
    }
    setClock((c) => c.since !== null ? c : { ...c, since: Date.now(), now: Date.now() });
    const timer = setInterval(() => setClock((c) => ({ ...c, now: Date.now() })), 100);
    return () => clearInterval(timer);
  }, [active]);
  return <>{clockText(clock.spent + (clock.since === null ? 0 : clock.now - clock.since))}</>;
}

/** The icon a journey badge wears for the kind of step it was. */
const stepIcon = (line: CrawlLine) =>
  line.kind === "visit" ? "🌐" : line.kind === "fill" ? "⌨️" : /cart|basket|bag/i.test(line.label) ? "🛒"
    : line.kind === "submit" || /checkout|order|pay/i.test(line.label) ? "📋" : "🖱️";

/**
 * Live agent mission HUD: telemetry, a step ticker of the crawler's real actions, and, when a
 * request fails, the intercepted defect with its click trail and a one-click sandbox repair that
 * runs through verification to an applied fix.
 */
export default function CrawlerHud(props: {
  state: CrawlState;
  /** The repair button's label: names Meta only when the engine reports the Meta Model API. */
  repairLabel: string;
  /** Why the defect cannot be repaired right now; null when the repair can start. */
  repairBlocked: string | null;
  /** The repair started from this defect, or null before one starts. */
  repair: MissionRepair | null;
  onRepair: () => void; onApply: () => void; onDismiss: () => void;
}) {
  const { state, repairLabel, repairBlocked, repair } = props;
  const tickerRef = useRef<HTMLOListElement>(null);
  /** The journey badge last picked, for the mission it was picked in. */
  const [picked, setPicked] = useState<{ mission: number; node: number } | null>(null);
  const running = crawlInFlight(state);
  const crawler = state.source === "playwright";

  // Keep the newest step in view without moving the page.
  useEffect(() => {
    const ticker = tickerRef.current;
    if (ticker) ticker.scrollTop = ticker.scrollHeight;
  }, [state.lines]);

  const defect = state.defect;
  const { steps, actions, screens, trail } = crawlSummary(state);
  const status = missionStatus(state, repair);
  const telemetry = crawler
    ? [["Screens Explored", screens], ["Actions", actions]] as const
    : [["Sessions", new Set(steps.map((line) => line.text.split(":")[0])).size], ["Requests", steps.length]] as const;
  const seismic = SEISMIC[status.tone];
  const working = running || Boolean(repair?.running || repair?.applying);
  // The journey ribbon: where the agent started, each step of the trail, and the request that broke.
  const at = (line: CrawlLine) => state.lines.indexOf(line);
  const first = trail[0];
  const journey = crawler && defect && first ? [
    ...(first.kind !== "visit" && first.page ? [{ icon: "🌐", label: first.page, line: at(first), impact: false }] : []),
    ...trail.map((line) => ({ icon: stepIcon(line), label: line.label, line: at(line), impact: false })),
    { icon: "💥", label: `${defect.method} ${defect.path}${defect.status ? ` ${defect.status}` : ""}`, line: at(trail.at(-1)!), impact: true },
  ] : [];
  const node = picked?.mission === state.startedAt ? picked.node : null;
  // The picked badge's step, as an index into `state.lines`.
  const focus = node === null ? null : journey[node]?.line ?? null;

  // Show a badge's step in the log, scrolling the log (and only as much of the page as needed).
  const reveal = (index: number) => {
    setPicked({ mission: state.startedAt, node: index });
    const item = tickerRef.current?.children[journey[index].line];
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    item?.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
  };

  return (
    <section className="hud shell" aria-labelledby="hud-h" data-phase={state.phase} data-seismic={seismic}>
      <div className="hud-frame">
        <Seismograph mode={seismic} />
        <div className="hud-head">
          <p className="hud-key" id="hud-h">Live Agent Mission · {crawler ? "Playwright" : "Direct HTTP check"}</p>
          <code className="hud-target">{state.target}</code>
          <button type="button" className="btn quiet tool hud-close" onClick={props.onDismiss}
            aria-label={running ? "Stop the agent and close" : "Close the mission"}>{running ? "Stop" : "Close"}</button>
        </div>

        <dl className="hud-telemetry">
          <div data-tone={status.tone}>
            <dt>Agent Status</dt>
            <dd><span className="hud-dot" aria-hidden="true" /><span role="status">{status.label}</span></dd>
          </div>
          {telemetry.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
          <div data-tone={defect ? "bad" : state.phase === "clean" ? "ok" : undefined}><dt>Defects</dt><dd>{defect ? 1 : 0}</dd></div>
          <div className="hud-clock" data-tone={working ? "active" : undefined}
            title="Agent time: the crawl, then the sandbox repair. Time spent waiting on you is not counted.">
            <dt>Elapsed</dt><dd><MissionClock key={state.startedAt} active={working} origin={state.startedAt} /></dd>
          </div>
        </dl>

        {state.fallbackReason && <p className="hud-note" data-phase="fallback">{state.fallbackReason}</p>}
        {state.note && <p className="hud-note" data-phase={state.phase}>{state.note}</p>}
        {state.lines.length === 0 && running && (
          <p className="hud-note">{state.phase === "retrying" ? "Waiting for the crawler to start…" : `Launching headless Chromium against ${state.target}…`}</p>
        )}

        {state.lines.length > 0 && (
          <ol ref={tickerRef} className="hud-ticker" role="log" aria-label="Agent steps" aria-live="polite" data-running={running || undefined}>
            {state.lines.map((line, i) => (
              <li key={i} data-ok={line.ok} data-kind={line.kind} data-focus={focus === i || undefined}>
                <span className="hud-pulse" aria-hidden="true" />
                <span className="hud-step">{line.n === null ? "[Scan]" : `[Step ${line.n}${line.last ? `–${line.last}` : ""}]`}</span>{" "}
                {line.text}
                {line.ok && line.kind !== "visit" && line.kind !== "scan" && line.kind !== "session" && <span className="muted"> (OK)</span>}
                {line.page && <span className="muted"> on {line.page}</span>}
                {line.caught && <strong className="hud-caught"> → <span aria-hidden="true">💥 </span>CAUGHT DEFECT: {line.caught}</strong>}
              </li>
            ))}
          </ol>
        )}
        {running && state.phase !== "retrying" && <p className="hud-cursor" aria-hidden="true">{state.phase === "fallback" ? "sending both sessions" : "agent hunting for bugs"}</p>}

        {state.phase === "clean" && (
          <p className="hud-shield">
            <span aria-hidden="true">✅ </span>
            {crawler
              ? `Exploration finished clean. 0 defects found across ${plural(screens, "screen")} and ${plural(actions, "action")}. A smoke signal for the flows explored, not a business-logic check.`
              : `Clean. 0 defects found in ${plural(telemetry[0][1], "fresh session")}.`}
          </p>
        )}

        {defect && (
          <div className="hud-defect" role="alert">
            <p className="hud-defect-kicker">Defect intercepted</p>
            <p className="hud-defect-title">
              <span className="hud-code">{defect.status ? `HTTP ${defect.status}` : "No response"}</span>
              <span className="sr-only"> on </span><span>{defect.method} {defect.path}</span>
            </p>
            <p className="hud-defect-trigger">
              Triggered by: {defect.trigger.kind} &ldquo;{defect.trigger.label}&rdquo;{defect.trigger.page && <> on <code>{defect.trigger.page}</code></>}
            </p>
            {journey.length > 0 && (
              <ol className="hud-ribbon" aria-label="User journey">
                {journey.map((badge, i) => (
                  <li key={i}>
                    <button type="button" className="hud-node" data-impact={badge.impact || undefined}
                      aria-current={node === i ? "step" : undefined} onClick={() => reveal(i)}
                      title={badge.impact ? "Show the step that broke in the agent log" : "Show this step in the agent log"}>
                      <span aria-hidden="true">{badge.icon}</span><span>{badge.label}</span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
            {trail.length > 1 && (
              <ol className="hud-trail" aria-label="Click trail">
                {trail.map((line, i) => <li key={i} data-ok={line.ok} data-focus={focus === at(line) || undefined}>{line.kind === "visit" || line.kind === "session" ? line.label : `“${line.label}”`}</li>)}
              </ol>
            )}
            {defect.fingerprint && <p className="hud-defect-fp"><code>{defect.fingerprint}</code></p>}
            {!repair && (
              <div className="hud-defect-actions">
                <button type="button" className="btn primary hud-repair" onClick={props.onRepair} disabled={repairBlocked !== null}
                  aria-describedby={repairBlocked ? "hud-blocked" : undefined}>
                  <span>{repairLabel} <span className="hud-repair-sub">(Sandbox Verified)</span></span><CtaIcon />
                </button>
                {repairBlocked && <span id="hud-blocked" className="hud-blocked">{repairBlocked}</span>}
              </div>
            )}
          </div>
        )}

        {repair && (
          <div className="hud-repair-state" data-tone={repair.verified ? "ok" : repair.running || repair.applying ? "active" : repair.outcome?.tone ?? "idle"} aria-live="polite">
            {repair.running ? (
              <p className="hud-repair-line"><span className="hud-dot" aria-hidden="true" />{repairLabel}: {repair.stage ?? "Starting"}…</p>
            ) : repair.verified ? (
              <>
                <p className="hud-repair-title">
                  <CtaIcon kind="check" className="hud-seal" />Fix verified{repair.checks ? `: ${repair.checks.passed}/${repair.checks.total} assertions passed` : ""} in {repair.sandbox}
                </p>
                {repair.applied ? (
                  <p className="hud-repair-line">
                    Applied to <code>{repair.applied.file}</code>.{" "}
                    {repair.applying ? "Waiting for the store to reload…"
                      : repair.applied.live ? <span data-tone={repair.applied.live.tone}>{repair.applied.live.text}</span>
                      : "Check it live to confirm."}
                  </p>
                ) : repair.canApply || repair.applying ? (
                  <div className="hud-defect-actions">
                    <button type="button" className="btn primary hud-apply" onClick={props.onApply} disabled={!repair.canApply}>
                      {repair.applying ? "Applying the verified fix…" : "Apply Verified Fix to Demo Store"}<CtaIcon kind="check" />
                    </button>
                  </div>
                ) : repair.applyNote ? <p className="hud-repair-line muted">{repair.applyNote}</p> : null}
              </>
            ) : repair.outcome ? (
              <p className="hud-repair-line">Repair ended: {repair.outcome.title}. See the run below for evidence.</p>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
