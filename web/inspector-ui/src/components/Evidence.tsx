import {
  STAGE_LABEL, TERMINAL, providerName,
  type Artifact, type Attempt, type Execution, type JobDetail, type JobEvent, type JobStage, type Tone,
} from "@/lib/faultline-api";

export const artifactUrl = (id: string) => `/api/faultline/artifacts/${encodeURIComponent(id)}`;
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour12: false });
const size = (n: number) =>
  n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const VERDICT = { passed: "Passed", failed: "Failed", error: "Runner error", timed_out: "Timed out" } as const;

const belongsTo = (a: Artifact, x: Execution) =>
  a.execution_id === x.report.execution_id || x.artifact_ids.includes(a.id);

function failureSignal(x: Execution): string {
  const observation = x.report.observations.find((o) => o.kind !== "assertion") ?? x.report.observations[0];
  if (observation) return observation.message;
  const failed = x.report.assertions.find((a) => !a.passed);
  return failed ? `${failed.id}: expected ${failed.expected}, observed ${failed.observed}` : "No failure detail recorded.";
}

/** Symptom and recorded cause in one line, e.g. "POST /api/checkout returned HTTP 500 · TypeError: …". */
function failureSummary(x: Execution): string {
  const http = x.report.observations.find((o) => o.kind === "http_error");
  const cause = x.report.observations.find((o) => o.kind === "server_exception");
  const status = http?.data?.status;
  const symptom = http && (typeof http.source === "string" && typeof status === "number"
    ? `${http.source} returned HTTP ${status}` : http.message);
  const parts = [symptom, cause?.message].filter((part): part is string => Boolean(part));
  return parts.length ? parts.join(" · ") : failureSignal(x);
}

const diffStat = (diff: string) => {
  const lines = diff.split("\n").filter((l) => !l.startsWith("+++") && !l.startsWith("---"));
  return `+${lines.filter((l) => l.startsWith("+")).length} −${lines.filter((l) => l.startsWith("-")).length}`;
};

/** The five judge-facing steps, mapped from orchestrator stages. */
export const STEP_LABELS = [
  "Reproduce the failure", "Propose a patch", "Pass the policy gates", "Verify the candidate", "Record evidence and clean up",
] as const;
const STEP_OF: Record<JobStage, number> = {
  preparing: 0, baseline: 0, diagnosing: 1, patch_validation: 2, activating: 3, verification: 3, cleanup: 4, completed: 4,
};
const STEP_DOING = [
  "A fresh browser in the isolated runtime places an order without a coupon.",
  "The repair provider is asked for a one-file diff. The prompt states the checkout rules, not the defect.",
  "The diff's path, source hash, size, syntax, and imports are checked before any code runs.",
  "A patched copy reruns the same browser journey plus pricing, coupon, and order-storage checks.",
  "The isolated runtime is disposed of and checksummed evidence is recorded.",
];
type StepState = "done" | "current" | "pending" | "failed" | "skipped";
const STEP_STATE_TEXT: Record<StepState, string> = {
  done: "complete", current: "in progress", pending: "not started", failed: "failed", skipped: "not reached",
};

/** Events can arrive over SSE before the next poll; the newest one is the most current stage. */
export const currentStep = (job: JobDetail["job"], events: JobEvent[]) => STEP_OF[events.at(-1)?.stage ?? job.stage] ?? STEP_OF[job.stage];

/** What happened at each step, read only from recorded data; nothing is inferred as passed. */
export function Pipeline(props: { detail: JobDetail; events: JobEvent[]; verification: Execution | null; verified: boolean }) {
  const { detail, events, verification, verified } = props;
  const { job, baseline, attempts, artifacts } = detail;
  const terminal = TERMINAL.has(job.state);
  const current = terminal ? -1 : currentStep(job, events);
  const latest = attempts.at(-1) ?? null;
  const v = latest?.validation_result ?? null;
  const verifiedNumber = attempts.find((a) => a.id === verification?.attempt_id)?.attempt_number;
  const prefix = (n: number | undefined) => (attempts.length > 1 && n ? `Attempt ${n}: ` : "");
  const noRepair = job.effective_mode === "detect" || job.outcome === "repair_unavailable" || job.outcome === "detected";

  type Recorded = { state: StepState; tone: Tone; text: string } | null;
  const recorded: Recorded[] = [
    baseline ? {
      state: baseline.report.verdict === "error" || baseline.report.verdict === "timed_out" ? "failed" : "done",
      tone: baseline.report.verdict === "failed" ? "bad" : baseline.report.verdict === "passed" ? "idle" : "warn",
      text: baseline.report.verdict === "failed" ? `Reproduced: ${failureSummary(baseline)}`
        : baseline.report.verdict === "passed" ? "The checkout worked, so there was nothing to repair."
        : `${VERDICT[baseline.report.verdict]} before the failure could be confirmed.`,
    } : null,
    latest ? {
      state: latest.parsed_diff ? "done" : "failed", tone: latest.parsed_diff ? "idle" : "bad",
      text: `${prefix(latest.attempt_number)}${typeof v?.provider === "string" && typeof v?.model === "string" ? providerName(v.provider, v.model) : "Provider not recorded"}${
        latest.parsed_diff ? ` · ${diffStat(latest.parsed_diff)} lines in ${typeof v?.target_file === "string" ? v.target_file : "one file"}` : " · no usable diff returned"}`,
    } : job.outcome === "model_error" ? { state: "failed", tone: "bad", text: "The repair provider returned no usable proposal." }
      : noRepair ? { state: "skipped", tone: "idle", text: "No patch requested: this was a detection-only run." } : null,
    v && typeof v.is_valid === "boolean" ? {
      state: v.is_valid ? "done" : "failed", tone: v.is_valid ? "ok" : "bad",
      text: v.is_valid ? `${prefix(latest?.attempt_number)}Scope, syntax, and AST safety policy passed before any code ran.`
        : `${prefix(latest?.attempt_number)}Rejected before execution: ${typeof v.error_message === "string" ? v.error_message : "policy violation"}`,
    } : null,
    verification ? {
      state: verification.report.verdict === "passed" ? "done" : "failed",
      tone: verification.report.verdict !== "passed" ? "bad" : verified ? "ok" : "warn",
      text: (() => {
        const list = verification.report.assertions;
        const failed = list.filter((a) => !a.passed).length;
        return `${prefix(verifiedNumber)}${list.length - failed} of ${list.length} checks passed in the isolated runtime${failed ? `; ${failed} failed` : ""}.`;
      })(),
    } : null,
    job.cleanup_status === "succeeded" ? { state: "done", tone: "idle", text: `Cleanup confirmed · ${artifacts.length} artifacts recorded with SHA-256 checksums.` }
      : job.cleanup_status === "failed" ? { state: "failed", tone: "bad", text: "Cleanup could not be confirmed, so new runs are held until a reset." }
      : null,
  ];

  return (
    <ol className="pipeline" aria-label="What FaultLine did in this run">
      {STEP_LABELS.map((label, i) => {
        const step = !terminal
          ? i < current ? recorded[i] ?? { state: "done" as const, tone: "idle" as const, text: "Complete." }
            : { state: i === current ? "current" as const : "pending" as const, tone: "idle" as const, text: STEP_DOING[i] }
          : recorded[i] ?? { state: "skipped" as const, tone: "idle" as const, text: "Not reached in this run." };
        return (
          <li key={label} data-state={step.state} data-step-tone={step.tone} aria-current={step.state === "current" ? "step" : undefined}>
            <span className="pipeline-mark" aria-hidden="true">{i + 1}</span>
            <strong>{label}<span className="sr-only"> ({STEP_STATE_TEXT[step.state]})</span></strong>
            <p>{step.text}</p>
          </li>
        );
      })}
    </ol>
  );
}

function Side(props: { label: string; run: Execution | null; tone: Tone; empty: string; shot?: Artifact }) {
  const { label, run, tone, empty, shot } = props;
  const assertions = run?.report.assertions ?? [];
  const passed = assertions.filter((a) => a.passed).length;
  return (
    <figure className="side" data-tone={tone}>
      <figcaption className="eyebrow">{label}</figcaption>
      {run ? (
        <>
          <p className="verdict">{VERDICT[run.report.verdict]}</p>
          {run.report.verdict === "passed" ? <p className="signal">{passed} of {assertions.length} checks passed</p> : (
            <>
              {assertions.length > 0 && <p className="signal">{assertions.length - passed} of {assertions.length} checks failed</p>}
              <p className="signal muted">{failureSummary(run)}</p>
            </>
          )}
          {shot && (
            // Shown only when the runner registered a screenshot; hidden if the bytes do not decode.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={artifactUrl(shot.id)}
              alt={`Browser screenshot captured during the ${run.phase} run`}
              loading="lazy"
              width={1440}
              height={900}
              onError={(e) => { e.currentTarget.hidden = true; }}
            />
          )}
        </>
      ) : (
        <p className="signal muted">{empty}</p>
      )}
    </figure>
  );
}

/** The product moment: observed failure on the left, observed verification on the right. */
export function Seam(props: {
  baseline: Execution | null; verification: Execution | null; verified: boolean;
  attemptNumber: number | null; artifacts: Artifact[];
  /** Current pipeline step while the job runs; null once it is terminal. */
  step: number | null;
}) {
  const { baseline, verification, verified, attemptNumber, artifacts, step } = props;
  const shot = (x: Execution | null) => (x ? artifacts.find((a) => a.role === "screenshot" && belongsTo(a, x)) : undefined);
  const baseTone: Tone = !baseline ? "idle" : baseline.report.verdict === "failed" ? "bad" : baseline.report.verdict === "passed" ? "idle" : "warn";
  const afterTone: Tone = verified ? "ok" : !verification ? "idle" : verification.report.verdict === "passed" ? "warn" : "bad";
  return (
    <div className="seam" data-verified={verified}>
      <Side label="Before · broken checkout" run={baseline} tone={baseTone} shot={shot(baseline)}
        empty={step === null ? "No baseline was recorded for this run."
          : step === 0 ? "Reproducing the checkout in a fresh browser…" : "Loading the recorded baseline…"} />
      <div className="seam-rule" aria-hidden="true" />
      <Side
        label={`After · tested fix${attemptNumber && attemptNumber > 1 ? `, attempt ${attemptNumber}` : ""}`}
        run={verification}
        tone={afterTone}
        empty={step === null ? "No patched candidate was verified for this run."
          : step < 3 ? "Waiting for a patched candidate to test…" : "Testing the patched candidate…"}
        shot={shot(verification)}
      />
    </div>
  );
}

export function Diff({ text, label }: { text: string; label: string }) {
  return (
    <pre className="code" tabIndex={0} aria-label={label}>
      {text.split("\n").map((line, i) => {
        const kind = line.startsWith("@@") ? "hunk" : /^(\+\+\+|---)/.test(line) ? "file"
          : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "ctx";
        return <span key={i} data-kind={kind}>{line || " "}</span>;
      })}
    </pre>
  );
}

/** What the independent gate told this attempt about the previous, rejected one. */
function PriorFeedback({ value, number }: { value: unknown; number: number }) {
  if (!value || typeof value !== "object") return null;
  const prior = value as { gate?: unknown; policy_error?: unknown; failed_check_count?: unknown; failed_checks?: unknown };
  const checks = Array.isArray(prior.failed_checks) ? prior.failed_checks.filter((c): c is string => typeof c === "string") : [];
  const count = typeof prior.failed_check_count === "number" ? prior.failed_check_count : checks.length;
  const gate = typeof prior.gate === "string" ? prior.gate.replaceAll("_", " ") : "an independent gate";
  return (
    <p className="explain feedback">
      <span className="eyebrow">Gate feedback from attempt {number - 1}</span>
      Rejected by {gate}
      {typeof prior.policy_error === "string" && <>: {prior.policy_error}</>}
      {count > 0 && <>. {count} failing {count === 1 ? "check" : "checks"} sent back as evidence{checks.length ? ":" : "."}</>}
      {checks.length > 0 && (
        <span className="checks">{checks.map((c) => <code key={c}>{c}</code>)}{count > checks.length && <span className="muted">+{count - checks.length} more</span>}</span>
      )}
    </p>
  );
}

function Policy({ result }: { result: Record<string, unknown> | null }) {
  if (!result || typeof result.is_valid !== "boolean") {
    return <p className="muted">Patch policy has not evaluated this attempt.</p>;
  }
  const flag = (label: string, value: unknown) => (
    <li data-tone={value === true ? "ok" : "bad"}>{label} {value === true ? "pass" : "fail"}</li>
  );
  return (
    <ul className="inline">
      {flag("Policy", result.is_valid)}
      {flag("Syntax", result.syntax_valid)}
      {flag("AST policy", result.ast_safe)}
      {typeof result.target_file === "string" && <li><code>{result.target_file}</code></li>}
      {result.diff_recounted === true && <li>hunk headers recounted from the model's diff</li>}
      {typeof result.error_message === "string" && <li data-tone="bad">{result.error_message}</li>}
    </ul>
  );
}

export function Attempts({ attempts, terminal }: { attempts: Attempt[]; terminal: boolean }) {
  if (!attempts.length) return null;
  return (
    <section className="block" aria-labelledby="attempts-h">
      <h3 id="attempts-h">{attempts.length > 1 ? `Proposed patches · ${attempts.length} attempts` : "Proposed patch"}</h3>
      <p className="block-note">The diff the provider returned, with the policy gate results. It was applied only to an isolated copy; nothing is deployed.</p>
      {[...attempts].reverse().map((a, index) => {
        const v = a.validation_result;
        const provider = typeof v?.provider === "string" && typeof v?.model === "string"
          ? providerName(v.provider, v.model) : "Provider not yet recorded";
        let explanation: string | null = null;
        try { explanation = a.raw_patch ? (JSON.parse(a.raw_patch) as { explanation?: string }).explanation ?? null : null; } catch {}
        return (
          <details key={a.id} open={index === 0} className="attempt">
            <summary>
              <strong>Attempt {a.attempt_number}</strong>
              <span className="muted">{provider}</span>
              <span className="muted">
                {a.prompt_tokens == null ? "usage not reported" : `${a.prompt_tokens} in · ${a.completion_tokens ?? "?"} out tokens`}
              </span>
              {typeof v?.generation_ms === "number" && (
                <span className="muted">generated in {(v.generation_ms / 1000).toFixed(1)} s</span>
              )}
              <span data-tone={a.outcome === "verified" ? "ok" : a.outcome ? "bad" : "idle"}>
                {a.outcome?.replaceAll("_", " ") ?? (terminal ? "no outcome recorded" : "in progress")}
              </span>
            </summary>
            <PriorFeedback value={v?.prior_feedback} number={a.attempt_number} />
            <Policy result={v} />
            {explanation && <p className="explain"><span className="eyebrow">Provider explanation</span>{explanation}</p>}
            {a.parsed_diff
              ? <Diff text={a.parsed_diff} label={`Unified diff from attempt ${a.attempt_number}`} />
              : <p className="muted">No diff was returned for this attempt.</p>}
          </details>
        );
      })}
    </section>
  );
}

export function Assertions({ runs }: { runs: { label: string; run: Execution }[] }) {
  if (!runs.length) return null;
  return (
    <section className="block" aria-labelledby="assertions-h">
      <h3 id="assertions-h">Assertions</h3>
      <div className="cols">
        {runs.map(({ label, run }) => {
          const list = run.report.assertions;
          const failed = list.filter((a) => !a.passed).length;
          return (
            <details key={run.report.execution_id}>
              <summary>{label} · {list.length - failed} of {list.length} passed{failed > 0 && ` · ${failed} failed`}</summary>
              {list.length === 0 ? <p className="muted">No assertions recorded.</p> : (
                <ul className="asserts">
                  {list.map((a) => (
                    <li key={a.id} data-tone={a.passed ? "ok" : "bad"}>
                      <span aria-hidden="true">{a.passed ? "✓" : "✕"}</span>
                      <span className="sr-only">{a.passed ? "Passed:" : "Failed:"}</span>
                      <code>{a.id}</code>
                      {!a.passed && <span className="muted">expected {a.expected} · observed {a.observed}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </details>
          );
        })}
      </div>
    </section>
  );
}

export function Artifacts(props: { artifacts: Artifact[]; executions: Execution[]; attempts: Attempt[] }) {
  const { artifacts, executions, attempts } = props;
  if (!artifacts.length) return null;
  const origin = (a: Artifact) => {
    const run = executions.find((x) => belongsTo(a, x));
    const attempt = attempts.find((t) => t.id === a.attempt_id);
    return run ? `${run.phase} run` : attempt ? `attempt ${attempt.attempt_number}` : "job";
  };
  return (
    <section className="block" aria-labelledby="artifacts-h">
      <h3 id="artifacts-h">Evidence</h3>
      <p className="block-note">Screenshots, Playwright traces, request logs, and reports from both runs, each recorded with a SHA-256 checksum.</p>
      <p className="evidence-actions">
        {artifacts.filter((a) => a.role === "proof_bundle_md" || a.role === "proof_bundle").map((a) => (
          <a key={a.id} className="btn" href={artifactUrl(a.id)} download>{a.role === "proof_bundle_md" ? "Download review summary" : "Download evidence bundle"}</a>
        ))}
      </p>
      <details>
        <summary>All artifacts · {artifacts.length} files</summary>
        <ul className="rows">
        {artifacts.map((a) => (
          <li key={a.id}>
            <strong>{a.role}</strong>
            {a.role === "proof_bundle" && <span className="muted">checksummed evidence bundle</span>}
            {a.role === "proof_bundle_md" && <span className="muted">review summary</span>}
            <span className="muted">{origin(a)}</span>
            <span className="muted">{a.content_type} · {size(a.size_bytes)}</span>
            <code title={a.sha256}>sha256 {a.sha256.slice(0, 12)}</code>
            <a href={artifactUrl(a.id)} download>
              Download<span className="sr-only"> {a.role} from {origin(a)}</span>
            </a>
          </li>
        ))}
        </ul>
      </details>
    </section>
  );
}

export function EventLog({ events, stream }: { events: JobEvent[]; stream: string }) {
  return (
    <section className="block" aria-labelledby="events-h">
      <h3 id="events-h">Events <span className="muted">{events.length} recorded · {stream === "closed" ? "complete · job finished" : `updates ${stream}`}</span></h3>
      <details>
        <summary>View event log</summary>
      {events.length === 0 ? <p className="muted">No events recorded yet.</p> : (
        <ol className="events" role="log" tabIndex={0} aria-label="Job events">
          {events.map((e) => (
            <li key={e.sequence}>
              <span className="muted">{String(e.sequence).padStart(3, "0")}</span>
              <time dateTime={e.timestamp}>{clock(e.timestamp)}</time>
              <span>{STAGE_LABEL[e.stage] ?? e.stage}</span>
              <span>{e.message} <code className="muted">{e.message_code}</code></span>
            </li>
          ))}
        </ol>
      )}
      </details>
    </section>
  );
}
