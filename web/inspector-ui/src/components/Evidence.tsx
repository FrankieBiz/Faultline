import {
  STAGES, STAGE_LABEL, TERMINAL, limitsName, providerName,
  type Artifact, type Attempt, type Execution, type Job, type JobEvent, type Tone,
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

export function Track({ job, events }: { job: Job; events: JobEvent[] }) {
  const terminal = TERMINAL.has(job.state);
  const reached = new Set<string>(events.map((e) => e.stage)).add(job.stage);
  return (
    <ol className="track" aria-label="Job stages">
      {STAGES.map((stage) => {
        const state =
          !terminal && stage === job.stage ? "current" : reached.has(stage) ? "reached" : terminal ? "skipped" : "pending";
        return (
          <li key={stage} data-state={state} aria-current={state === "current" ? "step" : undefined}>
            {STAGE_LABEL[stage]}
            <span className="sr-only"> ({state === "skipped" ? "not reached" : state})</span>
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
          <p className="signal">
            {run.report.verdict === "passed" ? `${passed} of ${assertions.length} assertions passed` : failureSignal(run)}
          </p>
          <p className="meta">
            {run.runtime_kind === "isolated-browser" ? "Isolated browser" : "Unverified runtime"} ·{" "}
            {limitsName(run.resource_limits)} ·{" "}
            {Math.round(run.report.duration_ms)} ms · snapshot {run.candidate_snapshot_sha256.slice(0, 12)}
          </p>
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
}) {
  const { baseline, verification, verified, attemptNumber, artifacts } = props;
  const shot = (x: Execution | null) => (x ? artifacts.find((a) => a.role === "screenshot" && belongsTo(a, x)) : undefined);
  const baseTone: Tone = !baseline ? "idle" : baseline.report.verdict === "failed" ? "bad" : baseline.report.verdict === "passed" ? "idle" : "warn";
  const afterTone: Tone = verified ? "ok" : !verification ? "idle" : verification.report.verdict === "passed" ? "warn" : "bad";
  return (
    <div className="seam" data-verified={verified}>
      <Side label="Before · baseline run" run={baseline} tone={baseTone} empty="The baseline has not run yet." shot={shot(baseline)} />
      <div className="seam-rule" aria-hidden="true" />
      <Side
        label={`After · verification${attemptNumber ? `, attempt ${attemptNumber}` : ""}`}
        run={verification}
        tone={afterTone}
        empty="No patched candidate has been verified for this job."
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
      {flag("AST safety", result.ast_safe)}
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
      <h3 id="attempts-h">Repair attempts</h3>
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
            <details key={run.report.execution_id} open={run.phase === "verification" || failed > 0}>
              <summary>{label} · {list.length - failed} of {list.length} passed</summary>
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
      <h3 id="artifacts-h">Artifacts</h3>
      <ul className="rows">
        {artifacts.map((a) => (
          <li key={a.id}>
            <strong>{a.role}</strong>
            <span className="muted">{origin(a)}</span>
            <span className="muted">{a.content_type} · {size(a.size_bytes)}</span>
            <code title={a.sha256}>sha256 {a.sha256.slice(0, 12)}</code>
            <a href={artifactUrl(a.id)} download>
              Download<span className="sr-only"> {a.role} from {origin(a)}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function EventLog({ events, stream }: { events: JobEvent[]; stream: string }) {
  return (
    <section className="block" aria-labelledby="events-h">
      <h3 id="events-h">Events <span className="muted">{events.length} recorded · stream {stream}</span></h3>
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
    </section>
  );
}
