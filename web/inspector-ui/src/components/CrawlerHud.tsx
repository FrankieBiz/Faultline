"use client";

import { useEffect, useRef } from "react";
import type { CheckRecord, CrawlEvent } from "@/lib/faultline-api";
import { checkVerdict } from "@/lib/faultline-api";

type Defect = Extract<CrawlEvent, { type: "defect" }>;

/** One ticker line: what was done and whether it held. */
export interface CrawlLine { n: number; text: string; page: string | null; ok: boolean }

/**
 * A chaos crawl as the HUD shows it. `source` says where every line came from: the Playwright
 * crawler's own events, or, when the crawler endpoint is not answering, the sessions of a
 * direct HTTP check sent in its place. Nothing here is inferred from clicks.
 */
export interface CrawlState {
  target: string;
  phase: "connecting" | "retrying" | "running" | "fallback" | "caught" | "clean" | "incomplete" | "failed";
  source: "playwright" | "check";
  scan: { buttons: number; forms: number; links: number } | null;
  lines: CrawlLine[];
  defect: (Omit<Defect, "type" | "trigger"> & { trigger: { kind: string; label: string; page: string | null } }) | null;
  /** Why a direct check stood in for the crawler; kept for as long as its result is shown. */
  fallbackReason: string | null;
  /** Retry progress or the final verdict, in one line. */
  note: string | null;
}

export const crawlInFlight = (state: CrawlState | null) =>
  state !== null && ["connecting", "retrying", "running", "fallback"].includes(state.phase);

export const startCrawl = (target: string): CrawlState =>
  ({ target, phase: "connecting", source: "playwright", scan: null, lines: [], defect: null, fallbackReason: null, note: null });

const VERB = { visit: "Visited", click: "Clicked", fill: "Filled", submit: "Submitted" } as const;

/** Folds one crawler event into the HUD state. */
export function applyCrawlEvent(state: CrawlState, event: CrawlEvent): CrawlState {
  const next: CrawlState = { ...state, phase: state.phase === "connecting" || state.phase === "retrying" ? "running" : state.phase, note: null };
  switch (event.type) {
    case "scan":
      return { ...next, scan: { buttons: event.buttons, forms: event.forms, links: event.links } };
    case "step": {
      const target = event.action === "visit" ? event.target : `"${event.target}"`;
      const text = `${VERB[event.action] ?? event.action} ${target} (${event.ok ? "OK" : event.note ?? "failed"})`;
      return { ...next, lines: [...next.lines, { n: event.n, text, page: event.action === "visit" ? null : event.page, ok: event.ok }] };
    }
    case "defect":
      return { ...next, phase: "caught", defect: { ...event } };
    case "done":
      return { ...next, phase: next.defect ? "caught" : "clean", note: next.defect ? null : `No failing request in ${event.steps} ${event.steps === 1 ? "step" : "steps"}.` };
    case "error":
      return { ...next, phase: "failed", note: event.message };
  }
}

/** Replaces the ticker with the sessions of the direct check that stood in for the crawler. */
export function crawlFromCheck(state: CrawlState, record: CheckRecord, title: string): CrawlState {
  let n = 0;
  const lines = record.sessions.flatMap((session, i): CrawlLine[] => session.requests.length
    ? session.requests.map((r) => ({ n: ++n, text: `Session ${i + 1}: ${r.method} ${r.path} → HTTP ${r.status}`, page: null, ok: r.status < 400 }))
    : [{ n: ++n, text: `Session ${i + 1}: ${record.method} ${new URL(record.url).pathname} → ${session.status ? `HTTP ${session.status}` : `no response${session.error ? ` (${session.error})` : ""}`}`, page: null, ok: session.status !== null && session.status < 400 }]);
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
  connecting: "Launching", retrying: "Waiting for crawler", running: "Crawling", fallback: "Direct check",
  caught: "Defect caught", clean: "No defect found", incomplete: "Ended early", failed: "Crawl failed",
};
const PHASE_TONE: Record<CrawlState["phase"], string> = {
  connecting: "active", retrying: "active", running: "active", fallback: "active",
  caught: "bad", clean: "idle", incomplete: "warn", failed: "warn",
};

/**
 * Live HUD of a Playwright chaos crawl: the DOM scan, a step ticker, and, when a request fails,
 * the intercepted defect with a one-click repair.
 */
export default function CrawlerHud(props: {
  state: CrawlState;
  /** The repair button's label: names Meta only when the engine reports the Meta Model API. */
  repairLabel: string;
  /** Why the defect cannot be repaired right now; null when the repair can start. */
  repairBlocked: string | null;
  onRepair: () => void; onDismiss: () => void;
}) {
  const { state, repairLabel, repairBlocked } = props;
  const tickerRef = useRef<HTMLOListElement>(null);
  const running = crawlInFlight(state);
  const scanning = state.source === "playwright" && (state.scan !== null || running);

  // Keep the newest step in view without moving the page.
  useEffect(() => {
    const ticker = tickerRef.current;
    if (ticker) ticker.scrollTop = ticker.scrollHeight;
  }, [state.lines.length]);

  const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
  const defect = state.defect;

  return (
    <section className="hud shell" aria-labelledby="hud-h" data-phase={state.phase}>
      <div className="hud-frame">
        <div className="hud-head">
          <p className="hud-key" id="hud-h">{state.source === "playwright" ? "Playwright chaos crawler" : "Direct HTTP check"}</p>
          <code className="hud-target">{state.target}</code>
          <span className="hud-phase" data-tone={PHASE_TONE[state.phase]} role="status">
            <span className="hud-dot" aria-hidden="true" />{PHASE_LABEL[state.phase]}
          </span>
          <button type="button" className="btn quiet tool hud-close" onClick={props.onDismiss}
            aria-label={running ? "Stop the crawl and close" : "Close the crawler"}>{running ? "Stop" : "Close"}</button>
        </div>

        {scanning && (
          <p className="hud-scan">
            <span className="hud-prompt" aria-hidden="true">$</span>
            {state.scan
              ? <>Scanning DOM… found {plural(state.scan.buttons, "button")} &amp; {plural(state.scan.forms, "form")}<span className="muted"> · {plural(state.scan.links, "link")}</span></>
              : state.phase === "retrying" ? "Waiting for the crawler to start…" : "Scanning DOM…"}
          </p>
        )}
        {state.fallbackReason && <p className="hud-note" data-phase="fallback">{state.fallbackReason}</p>}
        {state.note && <p className="hud-note" data-phase={state.phase}>{state.note}</p>}

        {state.lines.length > 0 && (
          <ol ref={tickerRef} className="hud-ticker" role="log" aria-label="Crawl steps" aria-live="polite">
            {state.lines.map((line) => (
              <li key={line.n} data-ok={line.ok}>
                <span className="hud-step">[Step {line.n}]</span> {line.text}
                {line.page && <span className="muted"> on {line.page}</span>}
              </li>
            ))}
          </ol>
        )}
        {running && state.phase !== "retrying" && <p className="hud-cursor" aria-hidden="true">{state.phase === "fallback" ? "sending both sessions" : "hunting for bugs"}</p>}

        {defect && (
          <div className="hud-defect" role="alert">
            <p className="hud-defect-title">
              <span aria-hidden="true">💥 </span>Defect Intercepted: {defect.status ? `HTTP ${defect.status}` : "no response"} on {defect.method} {defect.path}
            </p>
            <p className="hud-defect-trigger">
              Triggered by: {defect.trigger.kind} &ldquo;{defect.trigger.label}&rdquo;{defect.trigger.page && <> on <code>{defect.trigger.page}</code></>}
            </p>
            {defect.fingerprint && <p className="hud-defect-fp"><code>{defect.fingerprint}</code></p>}
            <div className="hud-defect-actions">
              <button type="button" className="btn primary hud-repair" onClick={props.onRepair} disabled={repairBlocked !== null}
                aria-describedby={repairBlocked ? "hud-blocked" : undefined}>
                <span aria-hidden="true">🛠️ </span>{repairLabel}
              </button>
              {repairBlocked && <span id="hud-blocked" className="hud-blocked">{repairBlocked}</span>}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
