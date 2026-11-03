"use client";

import { useId, useRef, useState, type KeyboardEvent } from "react";
import { GAUNTLET, HOLDOUT, MODEL_RUN, ORACLE_CHECKS, docUrl, type TrialOutcome } from "@/lib/judge-evidence";

const wrong = GAUNTLET.filter((p) => p.kind === "wrong");
const correct = GAUNTLET.filter((p) => p.kind === "correct");
const outOfPolicy = GAUNTLET.filter((p) => p.kind === "out_of_policy");
const symptomFalseGreens = wrong.filter((p) => p.symptom).length;
const faultlineRejected = wrong.filter((p) => !p.faultline).length;

const TRIAL: Record<TrialOutcome, { tone: "ok" | "bad"; mark: string; text: string }> = {
  verified: { tone: "ok", mark: "✓", text: "verified" },
  verified_on_retry: { tone: "ok", mark: "✓", text: "verified on attempt 2" },
  rejected: { tone: "bad", mark: "✕", text: "not verified; the oracle rejected the patch" },
};
const KIND = { correct: "correct", wrong: "plausible but wrong", out_of_policy: "out of policy" } as const;

/** 27 cells in the oracle's order; the defect's failing checks are lit. */
function OracleStrip({ failing }: { failing: string[] }) {
  const groups = [
    { key: "accept", label: "10 must succeed" },
    { key: "reject", label: "15 must be refused" },
    { key: "read", label: "2 must 404" },
  ] as const;
  return (
    <div className="strip" role="img" aria-label={`${failing.length} of ${ORACLE_CHECKS.length} oracle checks fail on the defective build`}>
      {groups.map((g) => (
        <div key={g.key} className="strip-group" data-group={g.key}>
          <div className="strip-cells">
            {ORACLE_CHECKS.filter((c) => c.group === g.key).map((c) => (
              <span key={c.id} className="strip-cell" data-fail={failing.includes(c.id) || undefined} title={c.id} />
            ))}
          </div>
          <span className="strip-label">{g.label}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * The evaluation corpus for judges: one gauntlet of eleven repairs judged two ways, then the ten
 * holdout defects as a vertical tablist, each with its contract, the defect itself, and what the
 * oracle and a model repair recorded.
 */
export default function EvaluationCorpus() {
  const ids = useId();
  const [selected, setSelected] = useState(0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const defect = HOLDOUT[selected];

  const onKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (!step && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const to = event.key === "Home" ? 0 : event.key === "End" ? HOLDOUT.length - 1 : (selected + step + HOLDOUT.length) % HOLDOUT.length;
    setSelected(to);
    tabRefs.current[to]?.focus();
  };

  return (
    <div className="corpus">
      <section aria-labelledby={`${ids}-g`}>
        <h3 id={`${ids}-g`} className="judge-h">Eleven repairs of one defect, judged two ways</h3>
        <p className="judge-note">
          Authored candidate patches for the registered checkout defect, recorded October 28, 2026 under both providers with identical results.
          The symptom check replays the storefront&apos;s failing request and accepts HTTP 201.
        </p>
        <div className="verdicts">
          <div className="verdict" data-tone="bad">
            <span className="verdict-key">Symptom check · the error went away</span>
            <strong><span aria-hidden="true">✕ </span>Accepted {symptomFalseGreens} of {wrong.length} wrong patches</strong>
            <span className="verdict-sub">False green: the 500 is gone, and the business contract is still broken.</span>
          </div>
          <div className="verdict" data-tone="ok">
            <span className="verdict-key">FaultLine oracle · 27 business checks on the sandboxed build</span>
            <strong><span aria-hidden="true">✓ </span>Rejected {faultlineRejected} of {wrong.length} wrong patches</strong>
            <span className="verdict-sub">
              Accepted {correct.length} of {correct.length} correct repairs, and refused {outOfPolicy.length} of {outOfPolicy.length} out-of-policy diffs before they ran.
            </span>
          </div>
        </div>
        <details className="gauntlet">
          <summary>All {GAUNTLET.length} candidate patches</summary>
          <div className="table-scroll">
            <table className="judge-table">
              <thead><tr><th scope="col">Patch</th><th scope="col">Kind</th><th scope="col">Symptom check</th><th scope="col">FaultLine</th><th scope="col">Failing checks</th></tr></thead>
              <tbody>
                {GAUNTLET.map((p) => (
                  <tr key={p.id}>
                    <th scope="row"><code>{p.id}</code><span className="muted">{p.title}</span></th>
                    <td>{KIND[p.kind]}</td>
                    <td data-tone={p.symptom === null ? undefined : p.symptom && p.kind === "wrong" ? "bad" : undefined}>
                      {p.symptom === null ? "not run" : p.symptom ? (p.kind === "wrong" ? "✕ accepted" : "accepted") : "rejected"}
                    </td>
                    <td data-tone={p.faultline ? "ok" : undefined}>{p.faultline ? "✓ accepted" : p.kind === "out_of_policy" ? "refused by policy" : "rejected"}</td>
                    <td className="num">{p.failing ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section aria-labelledby={`${ids}-h`}>
        <h3 id={`${ids}-h`} className="judge-h">Ten holdout defects</h3>
        <p className="judge-note">
          The registered defect plus nine single-change variants of the checkout route. The repair provider sees the source, the failing checks, and bounded logs,
          never the defect&apos;s name or the oracle&apos;s code. A case counts as verified only when all 27 checks pass.
        </p>
        <div className="holdout">
          <div className="holdout-list" role="tablist" aria-orientation="vertical" aria-label="Holdout defects">
            {HOLDOUT.map((d, i) => (
              <button key={d.id} ref={(el) => { tabRefs.current[i] = el; }} type="button" role="tab" id={`${ids}-t${i}`}
                aria-selected={i === selected} aria-controls={`${ids}-p`} tabIndex={i === selected ? 0 : -1}
                className="holdout-tab" onClick={() => setSelected(i)} onKeyDown={onKey}>
                <span className="holdout-index" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                <span className="holdout-name"><code>{d.id}</code><span>{d.defectClass}</span></span>
                <span className="holdout-count" aria-label={`${d.failing.length} failing checks`}>{d.failing.length}<span aria-hidden="true">/27</span></span>
              </button>
            ))}
          </div>

          <div className="holdout-detail" role="tabpanel" id={`${ids}-p`} aria-labelledby={`${ids}-t${selected}`} tabIndex={0}>
            <p className="holdout-eyebrow">{defect.defectClass} · <code>{defect.id}</code></p>
            <h4>{defect.title}</h4>
            <p className="holdout-contract"><span className="judge-key">Contract</span>{defect.contract}</p>

            <div className="holdout-change">
              <span className="judge-key">The defect <span className="muted">· struck lines are the healthy source</span></span>
              <pre className="defect-code" tabIndex={0} aria-label={`Source change that introduces ${defect.id}`}>
                {defect.change.map((line, i) => (
                  <span key={i} data-kind={line.startsWith("-") ? "healthy" : "defect"}>
                    <span className="sr-only">{line.startsWith("-") ? "Healthy line: " : "Defective line: "}</span>{line}
                  </span>
                ))}
              </pre>
            </div>

            <div>
              <span className="judge-key">Failing business invariants <span className="muted">· {defect.failing.length} of {ORACLE_CHECKS.length}</span></span>
              <OracleStrip failing={defect.failing} />
              <ul className="holdout-checks" aria-label="Failing checks">
                {defect.failing.map((c) => <li key={c}><code>{c}</code></li>)}
              </ul>
            </div>

            <dl className="holdout-verdicts">
              <div data-tone="ok">
                <dt>FaultLine oracle</dt>
                <dd><span aria-hidden="true">✓ </span>Caught: {defect.failing.length} failing {defect.failing.length === 1 ? "check" : "checks"} on the defective build, reproduced exactly in 2 of 2 trials.</dd>
              </div>
              <div data-tone={defect.trials.every((t) => t !== "rejected") ? "ok" : "bad"}>
                <dt>Model repair · {MODEL_RUN.provider}</dt>
                <dd>
                  {defect.trials.map((t, i) => (
                    <span key={i} className="trial" data-tone={TRIAL[t].tone}>
                      <span aria-hidden="true">{TRIAL[t].mark} </span>Trial {i + 1}: {TRIAL[t].text}
                    </span>
                  ))}
                  {defect.trials.includes("rejected") && <span className="trial-note">Neither patch was counted as a repair. The gates held.</span>}
                </dd>
              </div>
              {defect.id === "seeded_missing_coupon" && (
                <div data-tone="bad">
                  <dt>Symptom check</dt>
                  <dd><span aria-hidden="true">✕ </span>This is the defect the gauntlet above targets: the symptom check accepted {symptomFalseGreens} of {wrong.length} wrong patches.</dd>
                </div>
              )}
            </dl>
          </div>
        </div>
        <p className="judge-note">
          Model repairs: {MODEL_RUN.verified} of {MODEL_RUN.runs} runs verified on {MODEL_RUN.date}. {MODEL_RUN.note}{" "}
          <a href={docUrl(MODEL_RUN.source)} target="_blank" rel="noreferrer">Run record</a>
        </p>
      </section>
    </div>
  );
}
