"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import EvaluationCorpus from "@/components/EvaluationCorpus";
import { DOCS, META_LEDGER, RUBRIC, docUrl } from "@/lib/judge-evidence";
import { limitsStatusLabel, type Readiness } from "@/lib/faultline-api";

const TABS = [
  { key: "scorecard", label: "Scorecard & telemetry" },
  { key: "corpus", label: "Evaluation corpus" },
] as const;
type Tab = (typeof TABS)[number]["key"];

/** Live containment from readiness, beside what the recorded runs established. */
function Sandbox({ readiness, readinessError }: { readiness: Readiness | null; readinessError: string | null }) {
  const limits = readiness?.resource_limits ?? null;
  const enforced = limits?.enforcement_preflight === "passed" && limits.configured !== null;
  const tone = !readiness ? (readinessError ? "bad" : "active") : enforced ? "ok" : limits?.requested === "disabled" ? "warn" : "bad";
  const status = !readiness ? (readinessError ? "Engine unreachable: showing recorded evidence only" : "Checking the engine…")
    : limitsStatusLabel(limits);
  return (
    <section className="judge-section" aria-labelledby="judge-sandbox-h">
      <h3 id="judge-sandbox-h" className="judge-h">Sandbox verification</h3>
      <p className="sandbox-live" data-tone={tone} role="status">
        <span className="readiness-dot" aria-hidden="true" />
        <span className="judge-key">This engine, now</span>
        <span>{status}</span>
      </p>
      <ul className="judge-facts">
        <li><strong>Bubblewrap</strong> Every candidate backend runs in its own Linux namespaces; trusted browser and HTTP checks run outside it.</li>
        <li><strong>cgroup v2</strong> One aggregate scope per run: 512 MiB, no swap, 64 tasks, one CPU, read back from the kernel at every launch.</li>
        <li><strong>Fails closed</strong> Readiness requires adversarial memory-hog (OOM killed) and task-hog probes to be contained before any job runs.</li>
        <li><strong>Recorded</strong> 48 of 48 and 19 of 19 evaluation sessions ran under kernel-verified limits, as did both executions in the retained Meta job.</li>
      </ul>
      <p className="judge-note">Containment is namespaces plus cgroup limits on a shared kernel, not a VM. The sandbox confines a candidate; the business checks decide whether it is right.</p>
    </section>
  );
}

function Scorecard({ readiness, readinessError }: { readiness: Readiness | null; readinessError: string | null }) {
  return (
    <div className="scorecard">
      <section className="judge-section" aria-labelledby="judge-rubric-h">
        <h3 id="judge-rubric-h" className="judge-h">Official 100-point rubric</h3>
        <div className="rubric-bar" aria-hidden="true">
          {RUBRIC.map((r) => <span key={r.name} style={{ flexGrow: r.weight }}><b>{r.weight}</b>{r.name}</span>)}
        </div>
        <ol className="rubric">
          {RUBRIC.map((r) => (
            <li key={r.name}>
              <span className="rubric-weight">{r.weight}<span>%</span></span>
              <div>
                <h4>{r.name}</h4>
                <p>{r.evidence}</p>
                <a href={docUrl(r.doc.path)} target="_blank" rel="noreferrer">{r.doc.label}<span className="sr-only"> (opens in a new tab)</span></a>
              </div>
            </li>
          ))}
        </ol>
        <p className="judge-note">Weights from the October 26 judging webinar; each criterion is scored 0 to 10. The scores are the judges&apos; to give. FaultLine claims none.</p>
      </section>

      <section className="judge-section" aria-labelledby="judge-meta-h">
        <h3 id="judge-meta-h" className="judge-h">Live Meta Model API ledger</h3>
        <dl className="ledger-stats">
          <div data-tone="ok"><dt>Trials verified</dt><dd>{META_LEDGER.trials.length}/{META_LEDGER.trials.length}</dd><span>all on attempt 1</span></div>
          <div data-tone="ok"><dt>Assertions</dt><dd>44/44</dd><span>in every trial</span></div>
          <div><dt>Median wall time</dt><dd>{META_LEDGER.medianSeconds} s</dd><span>{META_LEDGER.rangeSeconds[0]} to {META_LEDGER.rangeSeconds[1]} s</span></div>
          <div><dt>Policy rejections</dt><dd>{META_LEDGER.policyRejections}</dd><span>cleanup confirmed 3 of 3</span></div>
        </dl>
        <div className="table-scroll">
          <table className="judge-table">
            <caption className="sr-only">Meta trials recorded on {META_LEDGER.date}</caption>
            <thead><tr><th scope="col">Trial</th><th scope="col">Job</th><th scope="col">Wall time</th><th scope="col">Assertions</th><th scope="col">Tokens in+out</th></tr></thead>
            <tbody>
              {META_LEDGER.trials.map((t, i) => (
                <tr key={t.job}>
                  <th scope="row">{i + 1}</th><td><code>{t.job}</code></td><td className="num">{t.seconds.toFixed(1)} s</td>
                  <td data-tone="ok">✓ {t.assertions}</td><td className="num">{t.tokens}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="judge-note">
          Meta <code>{META_LEDGER.model}</code> wrote every patch, recorded {META_LEDGER.date}. The ledger script refuses any non-Meta response.
          Scope: one registered scenario (<code>{META_LEDGER.scenario}</code>), a small sample rather than a reliability rate.{" "}
          <a href={docUrl(META_LEDGER.source)} target="_blank" rel="noreferrer">Ledger record</a>
        </p>
      </section>

      <Sandbox readiness={readiness} readinessError={readinessError} />

      <section className="judge-section" aria-labelledby="judge-docs-h">
        <h3 id="judge-docs-h" className="judge-h">Read the records</h3>
        <ul className="judge-docs">
          {DOCS.map((d) => (
            <li key={d.path}>
              <a href={docUrl(d.path)} target="_blank" rel="noreferrer">
                <span>{d.label}<span className="sr-only"> (opens in a new tab)</span></span>
                <code>{d.path}</code>
              </a>
              <span className="muted">{d.note}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/**
 * The judge's drawer: rubric, live Meta ledger, sandbox status, and the evaluation corpus.
 * Like the CLI guide, the dialog owns its open state; each new `request` opens it. The panels
 * mount only while it is open, so recorded Meta evidence is never mistaken for the live engine's.
 */
export default function JudgeEvidence({ request, readiness, readinessError }: {
  request: number; readiness: Readiness | null; readinessError: string | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const ids = useId();
  const [tab, setTab] = useState<Tab>("scorecard");
  const [open, setOpen] = useState(false);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || request === 0 || dialog.open) return;
    dialog.showModal();
    setOpen(true);
  }, [request]);

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = TABS.findIndex((t) => t.key === tab);
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const to = event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (index + step + TABS.length) % TABS.length;
    setTab(TABS[to].key);
    tabRefs.current[to]?.focus();
  };

  return (
    <dialog ref={ref} className="judge-drawer" aria-labelledby={`${ids}-h`} onClose={() => setOpen(false)}>
      <div className="judge">
        <div className="judge-head">
          <div>
            <p className="tag" data-tone="active">For judges</p>
            <h2 id={`${ids}-h`}>Judge scorecard &amp; telemetry</h2>
          </div>
          <button type="button" className="btn quiet" onClick={() => ref.current?.close()}>Close</button>
        </div>
        <div className="gate-tabs judge-tabs" role="tablist" aria-label="Judge evidence">
          {TABS.map((t, i) => (
            <button key={t.key} ref={(el) => { tabRefs.current[i] = el; }} type="button" role="tab" className="gate-tab"
              id={`${ids}-${t.key}`} aria-selected={tab === t.key} aria-controls={`${ids}-panel`} tabIndex={tab === t.key ? 0 : -1}
              onClick={() => setTab(t.key)} onKeyDown={onTabKey}>
              {t.label}
            </button>
          ))}
        </div>
        <div id={`${ids}-panel`} role="tabpanel" aria-labelledby={`${ids}-${tab}`}>
          {open && (tab === "scorecard" ? <Scorecard readiness={readiness} readinessError={readinessError} /> : <EvaluationCorpus />)}
        </div>
      </div>
    </dialog>
  );
}
