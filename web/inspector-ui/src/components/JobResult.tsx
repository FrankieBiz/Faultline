import type { RefObject } from "react";
import { Artifacts, Assertions, Attempts, EventLog, Pipeline, STEP_LABELS, Seam, currentStep } from "@/components/Evidence";
import {
  OUTCOME, TERMINAL, limitsName, providerName, providerNote,
  type JobDetail, type JobEvent, type Tone,
} from "@/lib/faultline-api";

/** Verification holds only with a failed isolated baseline, a passing candidate, and confirmed cleanup. */
export function summarizeJob(detail: JobDetail | null) {
  const job = detail?.job ?? null;
  const latest = detail?.attempts.at(-1) ?? null;
  const verifications = detail?.executions.filter((x) => x.phase === "verification") ?? [];
  const verification = verifications.findLast((x) => x.attempt_id === latest?.id) ?? verifications.at(-1) ?? null;
  const verifiedAttempt = detail?.attempts.find((a) => a.id === verification?.attempt_id) ?? null;
  const evidenceVerified = verification?.runtime_kind === "isolated-browser" && detail?.baseline?.runtime_kind === "isolated-browser";
  const verified = Boolean(evidenceVerified && detail?.baseline?.report.verdict === "failed" && job?.state === "succeeded"
    && job.cleanup_status === "succeeded" && job.outcome === "verified" && verification?.report.verdict === "passed");
  const legacy = job?.outcome === "verified" && !verified;
  const outcome = legacy
    ? { tone: "warn" as Tone, title: "Unverified result", detail: "This record does not establish a failed isolated baseline, passing candidate, and successful cleanup. Run a new job to collect current evidence." }
    : job?.outcome ? OUTCOME[job.outcome] : null;
  return { job, verification, verifiedAttempt, verified, outcome };
}

export default function JobResult(props: {
  detail: JobDetail; events: JobEvent[]; stream: string; running: boolean; pastRun: boolean;
  syncError: string | null; scenarioTitle: string | null;
  resultRef: RefObject<HTMLElement | null>; headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const { detail, events, stream, running, pastRun, syncError, scenarioTitle, resultRef, headingRef } = props;
  const { job, verification, verifiedAttempt, verified, outcome } = summarizeJob(detail);
  if (!job) return null;
  const terminal = TERMINAL.has(job.state);
  // Provider identity for this job comes from the recorded response, never from current readiness.
  const sourced = detail.attempts.findLast((a) => typeof a.validation_result?.provider === "string" && typeof a.validation_result?.model === "string");
  const jobProvider = sourced ? String(sourced.validation_result?.provider) : null;
  const jobSource = sourced ? providerName(String(sourced.validation_result?.provider), String(sourced.validation_result?.model)) : null;

  const downloadRecord = () => {
    const blob = new Blob([JSON.stringify(detail, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement("a"), { href: url, download: `faultline-job-${job.id}.json` }).click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <section className="job" ref={resultRef} aria-labelledby="job-h">
      <div className="result-heading">
        <p className="result-kicker">
          {pastRun ? "Past sandbox run" : running ? "Sandbox run in progress" : "Sandbox run result"}
          {scenarioTitle && <span className="muted"> for {scenarioTitle}</span>}
        </p>
        <h2 id="job-h" ref={headingRef} tabIndex={-1} aria-live="polite">{outcome?.title ?? `Running: ${STEP_LABELS[currentStep(job, events)]}`}</h2>
        <p className="lede">{verified
          ? `The baseline reproduced the failure. The proposed fix passed ${verification?.report.assertions.filter((a) => a.passed).length} of ${verification?.report.assertions.length} checks in the isolated runtime.`
          : outcome?.detail ?? "FaultLine is working through the scenario. This page updates automatically."}</p>
        {jobSource && jobProvider && (
          <p className="source-line" data-tone={jobProvider === "meta" ? "idle" : "warn"}>
            <span className="source-key">Patch source</span>
            <span>{jobSource}</span>
            {providerNote(jobProvider) && <span className="source-note">{providerNote(jobProvider)}</span>}
          </p>
        )}
        {job.repair_block_reason && <p className="muted">Repair blocked: <code>{job.repair_block_reason}</code></p>}
        {job.error_details && <p className="muted">Error detail: <code>{JSON.stringify(job.error_details).slice(0, 240)}</code></p>}
        {syncError && <p className="notice" role="status">Updates interrupted: {syncError} Retrying.</p>}
      </div>
      <Pipeline detail={detail} events={events} verification={verification} verified={verified} />
      <Seam baseline={detail.baseline} verification={verification} verified={verified}
        step={running ? currentStep(job, events) : null}
        attemptNumber={verifiedAttempt?.attempt_number ?? null} artifacts={detail.artifacts} />
      <Attempts attempts={detail.attempts} terminal={terminal} />
      <Artifacts artifacts={detail.artifacts} executions={detail.executions} attempts={detail.attempts} />
      <details className="technical-details">
        <summary>Explore the full run details</summary>
        <dl className="facts">
          <div><dt>Run</dt><dd title={job.id}>{job.id.slice(0, 8)}</dd></div>
          <div><dt>Scenario</dt><dd>{job.scenario_id}</dd></div>
          <div><dt>State</dt><dd>{job.state}</dd></div>
          <div><dt>Cleanup</dt><dd data-tone={job.cleanup_status === "failed" ? "bad" : undefined}>{job.cleanup_status.replace("_", " ")}</dd></div>
          <div><dt>Duration</dt><dd>{terminal ? `${((Date.parse(job.updated_at) - Date.parse(job.created_at)) / 1000).toFixed(1)} s` : "in progress"}</dd></div>
          <div><dt>Live updates</dt><dd>{stream === "closed" ? "Complete · job finished" : stream}</dd></div>
        </dl>
        {[detail.baseline, verification].filter((run) => run !== null).map((run) => (
          <p className="muted" key={run.report.execution_id}>{run.phase === "baseline" ? "Before" : "Candidate"}: {run.runtime_kind === "isolated-browser" ? "Isolated browser" : "Unverified runtime"} · {limitsName(run.resource_limits)} · {Math.round(run.report.duration_ms)} ms · snapshot <code>{run.candidate_snapshot_sha256.slice(0, 12)}</code></p>
        ))}
        <Assertions runs={[
          ...(detail.baseline ? [{ label: "Baseline", run: detail.baseline }] : []),
          ...(verification ? [{ label: `Verification, attempt ${verifiedAttempt?.attempt_number ?? "?"}`, run: verification }] : []),
        ]} />
        <EventLog events={events} stream={stream} />
        <p className="record"><button type="button" className="btn quiet" onClick={downloadRecord}>Download job record (JSON)</button><span className="muted">The exact orchestrator response for this job, unedited.</span></p>
      </details>
    </section>
  );
}
