"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AuthoredPreview from "@/components/AuthoredPreview";
import { Artifacts, Assertions, Attempts, EventLog, Pipeline, STEP_LABELS, Seam, currentStep } from "@/components/Evidence";
import {
  ApiError, OUTCOME, REASON, TERMINAL, api, limitsName, limitsStatusLabel, providerLabel, providerName, providerNote,
  type Job, type JobDetail, type JobEvent, type Readiness, type Tone,
} from "@/lib/faultline-api";

const SCENARIO_ID = "scripted_checkout_repair";
const POLL_MS = 1500;

type Stream = "idle" | "live" | "reconnecting" | "closed";
type Busy = "submit" | "cancel" | "reset" | null;

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Unexpected client error.");
// The controller requires a UUID. randomUUID exists only in secure contexts (not plain http on a LAN IP),
// so build an RFC 4122 v4 UUID from getRandomValues, which is available everywhere.
const newKey = () => {
  if (typeof globalThis.crypto.randomUUID === "function") return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

export default function Inspector({ storefrontUrl }: { storefrontUrl: string }) {
  const resultRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const scrollToResult = useRef(false);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [pastRun, setPastRun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [stream, setStream] = useState<Stream>("idle");
  const [loaded, setLoaded] = useState(false);
  const [history, setHistory] = useState<Job[]>([]);
  const [historyProviders, setHistoryProviders] = useState<Record<string, string>>({});
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<{ tone: Tone; text: string } | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const refreshReadiness = useCallback(async () => {
    try {
      setReadiness(await api<Readiness>("readiness"));
      setReadinessError(null);
    } catch (e) {
      setReadiness(null);
      setReadinessError(errorText(e));
    }
  }, []);

  const mergeEvents = useCallback((incoming: JobEvent[]) => {
    setEvents((current) => {
      const bySequence = new Map(current.map((e) => [e.sequence, e]));
      for (const e of incoming) bySequence.set(e.sequence, e);
      return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
    });
  }, []);

  const follow = useCallback((id: string, past = false) => {
    setPastRun(past);
    setDetail(null);
    setEvents([]);
    setStream("idle");
    setSyncError(null);
    setJobId(id);
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const { jobs } = await api<{ jobs: Job[] }>("jobs?limit=10");
      setHistory(jobs);
      setHistoryError(null);
      // List records omit provider identity; read the retained response metadata.
      void Promise.all(jobs.map(async (entry) => {
        try {
          const record = await api<JobDetail>(`jobs/${encodeURIComponent(entry.id)}`);
          const response = record.attempts.findLast((a) => typeof a.validation_result?.provider === "string");
          const v = response?.validation_result;
          return [entry.id, typeof v?.provider === "string" && typeof v.model === "string"
            ? providerName(v.provider, v.model) : "No provider response recorded"];
        } catch { return [entry.id, "Provider record unavailable"]; }
      })).then((labels) => setHistoryProviders(Object.fromEntries(labels)));
      return jobs;
    } catch (e) {
      setHistoryError(errorText(e));
      return [];
    }
  }, []);

  // After a reload, the newest server-side job is the one to show and, if unfinished, reattach to.
  useEffect(() => {
    let live = true;
    void refreshReadiness();
    refreshHistory()
      .then((jobs) => { if (live && jobs[0] && !TERMINAL.has(jobs[0].state)) follow(jobs[0].id); })
      .catch((e) => { if (live) setNotice({ tone: "bad", text: errorText(e) }); })
      .finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [refreshReadiness, refreshHistory, follow]);

  // Poll the job record and stream events until any terminal state, resuming by sequence cursor.
  useEffect(() => {
    if (!jobId) return;
    const path = `jobs/${encodeURIComponent(jobId)}`;
    let stopped = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    let retries = 0;
    let polling = false;
    let lastStage: string | null = null;

    const stop = () => {
      stopped = true;
      source?.close();
      clearTimeout(pollTimer);
      clearTimeout(retryTimer);
    };

    const open = () => {
      if (stopped) return;
      // The query cursor resumes replay even when the proxy does not forward Last-Event-ID.
      source = new EventSource(`/api/faultline/${path}/events?after=${cursor}`);
      source.onopen = () => setStream("live");
      source.addEventListener("job_event", (message) => {
        try {
          const event = JSON.parse((message as MessageEvent<string>).data) as JobEvent;
          cursor = Math.max(cursor, event.sequence);
          retries = 0;
          mergeEvents([event]);
          // A new stage means a new recorded result; read it now instead of waiting for the next poll.
          if (event.stage !== lastStage) {
            lastStage = event.stage;
            if (!polling && !stopped) {
              clearTimeout(pollTimer);
              pollTimer = setTimeout(poll, 50);
            }
          }
        } catch {}
      });
      source.onerror = () => {
        source?.close();
        if (stopped) return;
        setStream("reconnecting");
        retryTimer = setTimeout(open, Math.min(8000, 500 * 2 ** retries++));
      };
    };

    const poll = async () => {
      polling = true;
      try {
        const next = await api<JobDetail>(path);
        if (stopped) return;
        setDetail(next);
        setSyncError(null);
        mergeEvents(next.events);
        cursor = Math.max(cursor, ...next.events.map((e) => e.sequence));
        if (TERMINAL.has(next.job.state)) {
          stop();
          setStream("closed");
          void refreshReadiness();
          void refreshHistory();
          return;
        }
        if (!source) open();
      } catch (e) {
        if (stopped) return;
        setSyncError(errorText(e));
      } finally {
        polling = false;
      }
      if (!stopped) pollTimer = setTimeout(poll, POLL_MS);
    };

    void poll();
    return stop;
  }, [jobId, mergeEvents, refreshReadiness, refreshHistory]);

  useEffect(() => {
    if (detail && scrollToResult.current && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: "auto", block: "start" });
      // The run button is disabled while a job runs; keep keyboard and screen-reader focus on the result.
      headingRef.current?.focus({ preventScroll: true });
      scrollToResult.current = false;
    }
  }, [detail]);

  const start = async (mode: "repair" | "detect") => {
    setBusy("submit");
    setNotice(null);
    try {
      const accepted = await api<{ job_id: string; effective_mode: string; repair_block_reason: string | null }>("jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: SCENARIO_ID, idempotency_key: newKey(), mode }),
      });
      scrollToResult.current = true;
      follow(accepted.job_id);
      if (mode === "repair" && accepted.effective_mode === "detect") {
        setNotice({
          tone: "warn",
          text: `The orchestrator downgraded this run to detection only (${accepted.repair_block_reason ?? "provider unavailable"}).`,
        });
      }
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      void refreshReadiness();
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    if (!jobId) return;
    setBusy("cancel");
    try {
      await api(`jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("reset");
    setNotice(null);
    try {
      await api("reset", { method: "POST" });
      setNotice({ tone: "idle", text: "Environment reset. Readiness has been re-checked." });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
    } finally {
      setBusy(null);
      void refreshReadiness();
    }
  };

  const downloadRecord = () => {
    if (!detail) return;
    const blob = new Blob([JSON.stringify(detail, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    Object.assign(document.createElement("a"), { href: url, download: `faultline-job-${detail.job.id}.json` }).click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const job = detail?.job ?? null;
  const terminal = job ? TERMINAL.has(job.state) : false;
  // Until the first record arrives the job is assumed active, unless the record cannot be read at all.
  const running = jobId !== null && (job ? !terminal : syncError === null);
  const latest = detail?.attempts.at(-1) ?? null;
  const verifications = detail?.executions.filter((x) => x.phase === "verification") ?? [];
  const verification = verifications.findLast((x) => x.attempt_id === latest?.id) ?? verifications.at(-1) ?? null;
  const verifiedAttempt = detail?.attempts.find((a) => a.id === verification?.attempt_id) ?? null;
  const evidenceVerified = verification?.runtime_kind === "isolated-browser" && detail?.baseline?.runtime_kind === "isolated-browser";
  const verified = evidenceVerified && detail?.baseline?.report.verdict === "failed" && job?.state === "succeeded" && job.cleanup_status === "succeeded" && job.outcome === "verified" && verification?.report.verdict === "passed";
  const legacy = job?.outcome === "verified" && !verified;
  const outcome = legacy
    ? { tone: "warn" as Tone, title: "Unverified result", detail: "This record does not establish a failed isolated baseline, passing candidate, and successful cleanup. Run a new job to collect current evidence." }
    : job?.outcome ? OUTCOME[job.outcome] : null;

  // Provider identity for this job comes from the recorded response, never from current readiness.
  const sourced = detail?.attempts.findLast((a) => typeof a.validation_result?.provider === "string" && typeof a.validation_result?.model === "string");
  const jobProvider = sourced ? String(sourced.validation_result?.provider) : null;
  const jobSource = sourced ? providerName(String(sourced.validation_result?.provider), String(sourced.validation_result?.model)) : null;
  const readinessNote = readiness?.model ? providerNote(readiness.model.provider) : null;
  const readinessSourceTone: Tone = !readiness?.model ? "idle" : readiness.model.provider === "meta" && readiness.model.available ? "idle" : "warn";

  const status = readiness?.status;
  const gate =
    status === "ready" ? null
    : status === "detect_only"
      ? `The repair provider is unavailable (${readiness?.model?.reason ?? "no reason given"}). A detection run reproduces the failure without requesting a patch.`
    : status === "blocked" ? REASON[readiness?.reason ?? ""] ?? "Execution is blocked by the orchestrator."
    : readinessError ?? "Checking orchestrator readiness…";

  return (
    <>
      <a className="skip" href="#run">Skip to repair controls</a>
      <header className="top">
        <div className="shell top-row">
          <span className="wordmark"><span aria-hidden="true" className="glyph" />FaultLine</span>
          <span className="readiness" data-tone={status === "ready" ? "ok" : status === "detect_only" ? "warn" : "idle"}>
            {status === "ready" ? "Ready to run" : status === "detect_only" ? "Detection available" : status === "blocked" || readinessError ? "Needs attention" : "Checking setup…"}
          </span>
        </div>
      </header>

      <main className="shell">
        <section className="intro" id="run" aria-labelledby="title">
          <div className="intro-copy">
            <p className="intro-kicker">An interactive repair demonstration</p>
            <h1 id="title">Watch FaultLine fix a broken checkout.</h1>
            <p className="intro-description">A customer can’t place an order without a coupon. Watch FaultLine reproduce the crash, propose a fix, and test it against the checkout rules.</p>
            <div className="actions">
              <button type="button" className="btn primary run-button" onClick={() => start("repair")}
                disabled={status !== "ready" || running || busy !== null} aria-describedby={gate ? "gate" : undefined}>
                {busy === "submit" ? "Starting…" : running ? "Repair in progress…" : job ? "Run it again" : "Run the demo"}
              </button>
              {running && job && <button type="button" className="btn" onClick={cancel} disabled={busy !== null || job.cancel_requested}>
                {job.cancel_requested ? "Stopping…" : "Stop run"}
              </button>}
              {status === "detect_only" && !running && <button type="button" className="btn" onClick={() => start("detect")} disabled={busy !== null}>Run detection only</button>}
            </div>
            <p className="source-line" data-tone={readinessSourceTone}>
              <span className="source-key">Patch source</span>
              <span>{readiness ? providerLabel(readiness.model) : readinessError ? "Unknown until the orchestrator responds" : "Checking repair provider…"}</span>
              {readinessNote && <span className="source-note">{readinessNote}</span>}
            </p>
            {gate && <p id="gate" className="gate" role="status">{gate}</p>}
            {(readinessError || status === "blocked") && (
              <button type="button" className="btn quiet retry" onClick={refreshReadiness} disabled={busy !== null}>Check again</button>
            )}
            {notice && <p className="notice" data-tone={notice.tone} role="alert">{notice.text}</p>}
          </div>
          <aside className="how-it-works" aria-label="What happens during the demo">
            <h2>What happens</h2>
            <ol>
              <li><span>1</span><div><strong>Reproduce the failure</strong><p>A fresh, isolated browser places the order without a coupon and records the crash.</p></div></li>
              <li><span>2</span><div><strong>Propose and gate a patch</strong><p>The repair provider returns a one-file diff. Policy gates reject unsafe or malformed changes before anything runs.</p></div></li>
              <li><span>3</span><div><strong>Verify the candidate</strong><p>The patched copy reruns the checkout plus pricing and coupon checks. Evidence is kept for download.</p></div></li>
            </ol>
          </aside>
        </section>
        <p className="scope">This is a seeded demo. The candidate is tested in isolation; the storefront stays broken so you can repeat it. Nothing is deployed to production.</p>

        {!loaded ? <p className="empty" role="status">Checking for an active run…</p>
        : !jobId ? null
        : !job || !detail ? <p className="empty" role="status">{syncError ?? "Starting the demo…"}</p>
        : (
          <section className="job" ref={resultRef} aria-labelledby="job-h">
            <div className="result-heading">
              <p className="result-kicker">{pastRun ? "Past run" : running ? "Live demo" : "Run result"}</p>
              <h2 id="job-h" ref={headingRef} tabIndex={-1} aria-live="polite">{outcome?.title ?? `Running: ${STEP_LABELS[currentStep(job, events)]}`}</h2>
              <p className="lede">{verified
                ? `The original checkout failed. The proposed fix passed ${verification?.report.assertions.filter((a) => a.passed).length} of ${verification?.report.assertions.length} checks, including checkout and pricing.`
                : outcome?.detail ?? "FaultLine is working through the checkout. This page updates automatically."}</p>
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
        )}

        <details className="manual-walkthrough">
          <summary>Want to try the broken checkout yourself?</summary>
          <p>Open the store, add a Trail Mug, and enter a name, email, and address. Place the order without a coupon to see the failure; no payment is required. Then return here and run the demo.</p>
          <a className="btn" href={storefrontUrl} target="_blank" rel="noreferrer">Open seeded storefront</a>
        </details>

        <details className="history block">
          <summary>Past runs · {history.length} recent {history.length === 1 ? "run" : "runs"}</summary>
          {historyError && <p role="status">{historyError}</p>}
          {history.length === 0 ? <p className="muted">No past runs yet.</p> : <ul className="rows">
            {history.map((entry) => <li key={entry.id}>
              <button type="button" className="btn quiet" disabled={running || entry.id === jobId} onClick={() => { scrollToResult.current = true; follow(entry.id, true); }} aria-label={`Inspect job ${entry.id.slice(0, 8)}`}>
                {entry.id.slice(0, 8)}{entry.id === jobId ? " · selected" : ""}
              </button>
              <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
              <span>{entry.outcome?.replaceAll("_", " ") ?? entry.state}</span>
              <span className="muted">{historyProviders[entry.id] ?? "Reading provider record…"}</span>
            </li>)}
          </ul>}
          <button type="button" className="btn quiet" onClick={refreshHistory}>Refresh history</button>
        </details>
        <details className="setup-details">
          <summary>Setup and recovery</summary>
          <p>Containment: {readiness ? limitsStatusLabel(readiness.resource_limits) : "unknown"}</p>
          <button type="button" className="btn" onClick={reset} disabled={running || busy !== null || !readiness}>{busy === "reset" ? "Resetting…" : "Reset environment"}</button>{" "}
          <button type="button" className="btn quiet" onClick={refreshReadiness} disabled={busy !== null}>Refresh readiness</button>
        </details>
        <AuthoredPreview />
      </main>
      <footer className="shell foot"><span>FaultLine · Meta Global AI Developer Hackathon 2026 · Francis Bisignano</span><a href="https://github.com/FrankieBiz/Faultline">Source</a></footer>
    </>
  );
}
