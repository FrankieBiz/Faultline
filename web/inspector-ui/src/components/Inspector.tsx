"use client";

import { useCallback, useEffect, useState } from "react";
import AuthoredPreview from "@/components/AuthoredPreview";
import { Artifacts, Assertions, Attempts, EventLog, Seam, Track } from "@/components/Evidence";
import {
  ApiError, OUTCOME, REASON, STAGE_LABEL, TERMINAL, api, limitsStatusLabel, providerLabel, providerName,
  type Job, type JobDetail, type JobEvent, type Readiness, type Tone,
} from "@/lib/faultline-api";

const SCENARIO_ID = "scripted_checkout_repair";
const POLL_MS = 1500;

type Stream = "idle" | "live" | "reconnecting" | "closed";
type Busy = "submit" | "cancel" | "reset" | null;

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Unexpected client error.");
const newKey = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export default function Inspector({ storefrontUrl }: { storefrontUrl: string }) {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessError, setReadinessError] = useState<string | null>(null);
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

  const follow = useCallback((id: string) => {
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
      .then((jobs) => { if (live && jobs[0]) follow(jobs[0].id); })
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
      }
      pollTimer = setTimeout(poll, POLL_MS);
    };

    void poll();
    return stop;
  }, [jobId, mergeEvents, refreshReadiness, refreshHistory]);

  const start = async (mode: "repair" | "detect") => {
    setBusy("submit");
    setNotice(null);
    try {
      const accepted = await api<{ job_id: string; effective_mode: string; repair_block_reason: string | null }>("jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: SCENARIO_ID, idempotency_key: newKey(), mode }),
      });
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
  const verified = evidenceVerified && job?.state === "succeeded" && job.cleanup_status === "succeeded" && job.outcome === "verified" && verification?.report.verdict === "passed";
  const legacy = job?.outcome === "verified" && !evidenceVerified;
  const outcome = legacy
    ? { tone: "warn" as Tone, title: "Unverified historical result", detail: "This record predates isolated browser evidence. Its previous success label cannot establish that a repair was verified. Run a new job to collect current evidence." }
    : job?.outcome ? OUTCOME[job.outcome] : null;

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
          <dl className="strip" aria-label="Orchestrator readiness">
            <div>
              <dt>Orchestrator</dt>
              <dd data-tone={status === "ready" ? "ok" : status === "detect_only" ? "warn" : readiness || readinessError ? "bad" : "idle"}>
                {status?.replace("_", " ") ?? (readinessError ? "unavailable" : "checking")}
              </dd>
            </div>
            <div>
              <dt>Provider</dt>
              <dd>{readiness ? providerLabel(readiness.model) : "unknown"}</dd>
            </div>
            <div>
              <dt>Containment</dt>
              <dd data-tone={readiness?.resource_limits?.enforcement_preflight === "passed" ? "ok" : readiness?.resource_limits ? "warn" : "idle"}>
                {readiness ? limitsStatusLabel(readiness.resource_limits) : "unknown"}
              </dd>
            </div>
          </dl>
        </div>
      </header>

      <main className="shell">
        <section className="intro" id="run" aria-labelledby="title">
          <p className="eyebrow">BuggyShop · POST /api/checkout · apps/buggyshop-backend/app/routes/checkout.py</p>
          <h1 id="title">A checkout crash, repaired with proof.</h1>
          <p className="lede">
            A real browser reproduces the failure. The repair provider proposes a bounded patch.
            Independent checks verify the candidate. Inspect the browser evidence, regression results, and cleanup.
          </p>
          <ol className="journey" aria-label="Judge walkthrough">
            <li><a href={storefrontUrl} target="_blank" rel="noreferrer">Open seeded storefront</a>: add a Trail Mug and checkout without a coupon to see the failure.</li>
            <li>Run live repair here. The controller independently reproduces the failure and tests a patched candidate.</li>
            <li>Compare the before/after evidence and download the review summary or complete job record.</li>
          </ol>
          <p className="scope">The candidate is verified in isolation. The storefront stays seeded for repeatable demonstrations. No production deployment occurs.</p>
          <div className="actions">
            <button
              type="button"
              className="btn primary"
              onClick={() => start("repair")}
              disabled={status !== "ready" || running || busy !== null}
              aria-describedby={gate ? "gate" : undefined}
            >
              {busy === "submit" ? "Submitting…" : running ? "Job running…" : "Run live repair"}
            </button>
            {running && job && (
              <button type="button" className="btn" onClick={cancel} disabled={busy !== null || job.cancel_requested}>
                {job.cancel_requested ? "Cancellation requested" : "Cancel job"}
              </button>
            )}
            {status === "detect_only" && !running && (
              <button type="button" className="btn" onClick={() => start("detect")} disabled={busy !== null}>
                Run detection only
              </button>
            )}
            <button
              type="button"
              className={readiness?.quarantined ? "btn" : "btn quiet"}
              onClick={reset}
              disabled={running || busy !== null || !readiness}
            >
              {busy === "reset" ? "Resetting…" : "Reset environment"}
            </button>
            <button type="button" className="btn quiet" onClick={refreshReadiness} disabled={busy !== null}>
              Refresh readiness
            </button>
          </div>
          {gate && <p id="gate" className="gate" role="status">{gate}</p>}
          {notice && <p className="notice" data-tone={notice.tone} role="alert">{notice.text}</p>}
        </section>

        <details className="history block">
          <summary>Job history · {history.length} recent runs</summary>
          {historyError && <p role="status">{historyError}</p>}
          {history.length === 0 ? <p className="muted">No history available.</p> : (
            <ul className="rows">
              {history.map((entry) => (
                <li key={entry.id}>
                  <button type="button" className="btn quiet" disabled={running || entry.id === jobId}
                    onClick={() => follow(entry.id)} aria-label={`Inspect job ${entry.id.slice(0, 8)}`}>
                    {entry.id.slice(0, 8)}{entry.id === jobId ? " · selected" : ""}
                  </button>
                  <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
                  <span>{entry.outcome?.replaceAll("_", " ") ?? entry.state}</span>
                  <span className="muted">{historyProviders[entry.id] ?? "Reading provider record…"}</span>
                </li>
              ))}
            </ul>
          )}
          <button type="button" className="btn quiet" onClick={refreshHistory}>Refresh history</button>
        </details>

        {!loaded ? (
          <p className="empty">Loading the latest job…</p>
        ) : !jobId ? (
          <p className="empty">
            No jobs recorded yet.{" "}
            {status === "ready" ? "Run a live repair to create the first evidence record." : "Runs stay disabled until the orchestrator reports ready."}
          </p>
        ) : !job || !detail ? (
          <p className="empty" role="status">{syncError ?? `Loading job ${jobId.slice(0, 8)}…`}</p>
        ) : (
          <section className="job" aria-labelledby="job-h">
            <div className="job-head">
              <div>
                <p className="eyebrow">
                  Job <span title={job.id}>{job.id.slice(0, 8)}</span> · {job.requested_mode}
                  {job.effective_mode !== job.requested_mode && ` → ${job.effective_mode}`} · started{" "}
                  {new Date(job.created_at).toLocaleString()}
                </p>
                <h2 id="job-h" aria-live="polite">{outcome?.title ?? `Running · ${STAGE_LABEL[job.stage]}`}</h2>
                <p className="lede">{outcome?.detail ?? "Events stream from the orchestrator as each stage completes."}</p>
                {job.repair_block_reason && <p className="muted">Repair blocked: <code>{job.repair_block_reason}</code></p>}
                {job.error_details && (
                  <p className="muted">Error detail: <code>{JSON.stringify(job.error_details).slice(0, 240)}</code></p>
                )}
                {syncError && <p className="notice" role="status">Sync interrupted: {syncError} Retrying.</p>}
              </div>
              <dl className="facts">
                <div><dt>State</dt><dd>{job.state}</dd></div>
                <div>
                  <dt>Cleanup</dt>
                  <dd data-tone={job.cleanup_status === "failed" ? "bad" : undefined}>{job.cleanup_status.replace("_", " ")}</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>{terminal ? `${((Date.parse(job.updated_at) - Date.parse(job.created_at)) / 1000).toFixed(1)} s` : "in progress"}</dd>
                </div>
                <div><dt>Live updates</dt><dd>{stream === "closed" ? "Complete · job finished" : stream}</dd></div>
              </dl>
            </div>

            <Track job={job} events={events} />
            <Seam
              baseline={detail.baseline}
              verification={verification}
              verified={verified}
              attemptNumber={verifiedAttempt?.attempt_number ?? null}
              artifacts={detail.artifacts}
            />
            <Attempts attempts={detail.attempts} terminal={terminal} />
            <Assertions
              runs={[
                ...(detail.baseline ? [{ label: "Baseline", run: detail.baseline }] : []),
                ...(verification ? [{ label: `Verification, attempt ${verifiedAttempt?.attempt_number ?? "?"}`, run: verification }] : []),
              ]}
            />
            <Artifacts artifacts={detail.artifacts} executions={detail.executions} attempts={detail.attempts} />
            <EventLog events={events} stream={stream} />
            <p className="record">
              <button type="button" className="btn quiet" onClick={downloadRecord}>Download job record (JSON)</button>
              <span className="muted">The exact orchestrator response for this job, unedited.</span>
            </p>
          </section>
        )}

        <AuthoredPreview />
      </main>

      <footer className="shell foot">
        <span>FaultLine · Meta Global AI Developer Hackathon 2026 · Francis Bisignano</span>
        <a href="https://github.com/FrankieBiz/Faultline">Source</a>
      </footer>
    </>
  );
}
