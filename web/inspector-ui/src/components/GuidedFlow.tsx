import type { CheckRecord, StoreStatus, Tone } from "@/lib/faultline-api";
import { checkVerdict } from "@/lib/faultline-api";

function headline(store: StoreStatus): { tone: Tone; text: string } {
  if (store.state === "seeded") return { tone: "bad", text: "Checkout is broken: the seeded defect is live" };
  if (store.state === "patched") return { tone: "ok", text: `Checkout is fixed by run ${store.applied_job_id?.slice(0, 8)}` };
  if (store.state === "modified") return { tone: "warn", text: "Store source changed outside FaultLine" };
  return { tone: "warn", text: "Store source not found" };
}

/** What a step shows under its title: an evidence tone (or "active" while in flight) and one line. */
export type StepStatus = { tone: Tone | "active"; text: string };

/** The demo repair the guided flow drives, summarized from the run on screen. */
export interface FlowRun {
  /** "Repair with Meta" only when the engine reports the Meta Model API; never inferred. */
  label: string;
  /** How the patch is produced, e.g. "muse-spark-1.3 in a Bubblewrap sandbox". */
  source: string;
  running: boolean;
  /** The current pipeline step while running, e.g. "Verify the candidate". */
  stage: string | null;
  verified: boolean;
  /** Passing and total checks of the verified candidate. */
  checks: { passed: number; total: number } | null;
  /** The settled outcome of an unverified run. */
  outcome: { tone: Tone; title: string } | null;
  /** Why a repair cannot start right now, in a few words; null when it can. */
  blocked: string | null;
}

const httpStatus = (check: CheckRecord) => check.sessions.find((s) => s.status !== null)?.status ?? null;

/** The chaos crawler's run against the store, as step 1 reports it. */
export interface StoreHunt {
  /** True while the Playwright crawler is connecting or clicking through the store. */
  running: boolean;
  /** The page where the crawler caught the store's checkout defect, or null when it has not. */
  caughtOn: string | null;
}

/**
 * Demo Playground: the sample store's three-step story. Break it (the Playwright
 * chaos crawler clicks through the store until checkout returns HTTP 500, or a
 * direct live checkout when the crawler is unavailable), repair it in the sandbox, and apply the verified
 * fix so checkout returns HTTP 201. Each step's state is read from evidence
 * (store source, the latest live check, the run on screen), never from clicks.
 */
export default function GuidedFlow(props: {
  store: StoreStatus | null; error: string | null; storefrontUrl: string;
  /** The latest live check of the store's checkout, or null when none has run. */
  liveCheck: CheckRecord | null;
  /** Whether a live checkout check is declared, so step 3 (and step 1 without the crawler) can confirm in the live store. */
  canCheckLive: boolean;
  run: FlowRun;
  hunt: StoreHunt;
  /** A run whose evidence verifies a fix, or null when none is open. */
  verifiedJobId: string | null;
  /** `checking` is true only while the store's own checkout check is in flight. */
  busy: boolean; breaking: boolean; applying: boolean; confirming: boolean; reverting: boolean; checking: boolean;
  onBreak: () => void; onRepair: () => void; onApply: () => void;
  onRevert: () => void; onCheckLive: () => void; onRetry: () => void;
}) {
  const { store, error, storefrontUrl, liveCheck, canCheckLive, run, hunt, verifiedJobId, busy, breaking, applying, confirming, reverting, checking } = props;
  const state = store ? headline(store) : null;
  const fixed = store?.state === "patched";
  const live = liveCheck ? checkVerdict(liveCheck) : null;
  const status = liveCheck ? httpStatus(liveCheck) : null;
  const failingLive = live?.tone === "bad";

  const step3Done = fixed;
  const step2Done = fixed || run.verified;
  const caught = store?.state === "seeded" && hunt.caughtOn !== null;
  const step1Done = step2Done || run.running || caught || (store?.state === "seeded" && failingLive);
  const current = !step1Done ? 1 : !step2Done ? 2 : !step3Done ? 3 : null;

  const canBreak = store !== null && store.state !== "missing" && !busy;
  const canRepair = run.blocked === null && !busy;
  const canApply = store?.state === "seeded" && verifiedJobId !== null && !busy;
  const canRevert = store !== null && store.state !== "seeded" && store.state !== "missing" && !busy;

  const step1: StepStatus = hunt.running ? { tone: "active", text: "Playwright hunting for bugs…" }
    : breaking || (checking && store?.state === "seeded" && !confirming) ? { tone: "active", text: "Sending a real checkout…" }
    : caught ? { tone: "bad", text: `Bug caught on ${hunt.caughtOn}!` }
    : store?.state === "seeded" && liveCheck ? { tone: live?.tone ?? "idle", text: `HTTP ${status ?? "no response"} · ${failingLive ? "checkout crashes" : live?.title.toLowerCase()}` }
    : fixed ? { tone: "idle", text: "Reverts the fix, then crawls again" }
    : { tone: "idle", text: "Clicks through the store until checkout fails" };
  const step2: StepStatus = run.running ? { tone: "active", text: `${run.stage ?? "Starting"}…` }
    : run.verified && run.checks ? { tone: "ok", text: `${run.checks.passed} of ${run.checks.total} checks passed` }
    : run.outcome ? { tone: run.outcome.tone, text: run.outcome.title }
    : run.blocked ? { tone: "warn", text: run.blocked }
    : { tone: "idle", text: run.source };
  const step3: StepStatus = applying ? { tone: "active", text: "Hot-patching the store…" }
    : confirming ? { tone: "active", text: "Waiting for the store to reload…" }
    : fixed && liveCheck && live?.tone === "ok" ? { tone: "ok", text: `HTTP ${status} · checkout works` }
    : fixed ? { tone: "ok", text: "Applied · check checkout live to confirm" }
    : verifiedJobId ? { tone: "idle", text: `Writes run ${verifiedJobId.slice(0, 8)}'s verified fix to the store` }
    : { tone: "idle", text: "Unlocks after a verified repair" };

  const steps = [
    { n: 1, title: "Break it", detail: "Run Playwright crawler to reproduce defect", status: step1, done: step1Done, enabled: canBreak, onClick: props.onBreak },
    { n: 2, title: run.label, detail: "Sandboxed, verified by every check", status: step2, done: step2Done, enabled: canRepair, onClick: props.onRepair },
    { n: 3, title: "Apply fix", detail: "Checkout returns HTTP 201", status: step3, done: step3Done, enabled: canApply, onClick: props.onApply },
  ];

  return (
    <section className="playground" data-tone={state?.tone ?? "idle"} aria-labelledby="store-h">
      <div className="shell">
        <div className="playground-head">
          <div className="store-status">
            <p className="store-key">Demo Playground <span className="muted">· Sample Store</span></p>
            <h2 id="store-h" aria-live="polite">{state?.text ?? (error ? "Store state unavailable" : "Reading store state…")}</h2>
          </div>
          {store ? (
            <div className="store-meta">
              <span><code>{store.target_file}</code> at <a href={store.url} target="_blank" rel="noreferrer">{store.url.replace(/^https?:\/\//, "")}</a></span>
              <a href={storefrontUrl} target="_blank" rel="noreferrer">Open storefront</a>
              {canCheckLive && (
                <button type="button" className="btn quiet inline-btn" onClick={props.onCheckLive} disabled={busy}>
                  {checking && !breaking && !confirming ? "Checking…" : "Check checkout live"}
                </button>
              )}
              <button type="button" className="btn quiet inline-btn" onClick={props.onRevert} disabled={!canRevert}>
                {reverting && !breaking ? "Reverting…" : "Revert store"}
              </button>
            </div>
          ) : error ? (
            <p className="store-meta">{error} <button type="button" className="btn quiet inline-btn" onClick={props.onRetry}>Check again</button></p>
          ) : null}
        </div>
        <ol className="flow" aria-label="Guided demo">
          {steps.map((step) => {
            const phase = step.status.tone === "active" ? "active" : step.done ? "done" : step.n === current ? "current" : "pending";
            return (
              <li key={step.n} className="flow-step" data-state={phase} aria-current={step.n === current ? "step" : undefined}>
                <button type="button" className="flow-button" onClick={step.onClick} disabled={!step.enabled}
                  aria-labelledby={`flow-${step.n}-t`} aria-describedby={`flow-${step.n}-k flow-${step.n}-d flow-${step.n}-s`}>
                  <span key={phase} className="flow-mark" aria-hidden="true">{phase === "done" ? "✓" : step.n}</span>
                  <span className="flow-copy">
                    <span id={`flow-${step.n}-k`} className="flow-kicker">Step {step.n}{phase === "done" && <span className="sr-only">, done</span>}</span>
                    <span id={`flow-${step.n}-t`} className="flow-title">{step.title}</span>
                    <span id={`flow-${step.n}-d`} className="flow-detail">{step.detail}</span>
                    <span id={`flow-${step.n}-s`} className="flow-status" data-tone={step.status.tone}>{step.status.text}</span>
                  </span>
                  {phase === "current" && step.enabled && <span className="flow-go" aria-hidden="true">Start →</span>}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
