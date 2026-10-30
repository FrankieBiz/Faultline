"use client";

import { useCallback, useEffect, useState } from "react";
import AuthoredPreview from "@/components/AuthoredPreview";
import { Artifacts, Assertions, Attempts, EventLog, Seam, Track } from "@/components/Evidence";
import {
  ApiError, OUTCOME, REASON, STAGE_LABEL, TERMINAL, api, limitsStatusLabel, providerLabel,
  type Job, type JobDetail, type JobEvent, type Readiness, type Tone,
} from "@/lib/faultline-api";

const SCENARIO_ID = "scripted_checkout_repair";
const POLL_MS = 1500;

type Stream = "idle" | "live" | "reconnecting" | "closed";
type Busy = "submit" | "cancel" | "reset" | "apply" | "revert" | null;

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Unexpected client error.");
const newKey = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export default function Inspector() {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [stream, setStream] = useState<Stream>("idle");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<{ tone: Tone; text: string } | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

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

  // After a reload, the newest server-side job is the one to show and, if unfinished, reattach to.
  useEffect(() => {
    let live = true;
    void refreshReadiness();
    api<{ jobs: Job[] }>("jobs?limit=1")
      .then(({ jobs }) => { if (live && jobs[0]) follow(jobs[0].id); })
      .catch((e) => { if (live) setNotice({ tone: "bad", text: errorText(e) }); })
      .finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [refreshReadiness, follow]);

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
  }, [jobId, mergeEvents, refreshReadiness]);

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

  const applyPatch = async (targetJobId: string) => {
    setBusy("apply");
    setNotice(null);
    try {
      await api(`jobs/${encodeURIComponent(targetJobId)}/apply`, { method: "POST" });
      setNotice({
        tone: "ok",
        text: "Verified patch applied to live store! BuggyShop (http://127.0.0.1:3000) is now working.",
      });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  const revertStore = async () => {
    setBusy("revert");
    setNotice(null);
    try {
      await api("revert", { method: "POST" });
      setNotice({
        tone: "warn",
        text: "Live store reverted to seeded defect. Checkout on port 3000 will now fail.",
      });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
    } finally {
      setBusy(null);
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

  useEffect(() => {
    if (!job || terminal) {
      setElapsed(null);
      return;
    }
    const start = Date.parse(job.created_at);
    const update = () => setElapsed(Math.max(0, (Date.now() - start) / 1000));
    update();
    const timer = setInterval(update, 100);
    return () => clearInterval(timer);
  }, [job, terminal]);

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
          <p className="eyebrow">BuggyShop · POST /api/checkout · Simulated Production Downtime: $59.90 / order · 100% conversion loss</p>
          <h1 id="title">A shopper submits checkout. The merchant receives no order.</h1>
          <p className="lede">
            A real browser reproduces the silent checkout crash ($59.90 cart loss). The Meta repair provider proposes a bounded patch under strict prompt containment.
            Independent Playwright assertions and AST policy verify the candidate in an isolated cgroup sandbox.
          </p>
          <div className="impact-strip" aria-label="Incident telemetry and differentiator">
            <span className="badge-loss">Simulated Loss: <strong>$59.90 / order</strong> · 100% drop-off</span>
            <span className="badge-diff">Evaluation Benchmark: <strong>Naive checks accepted 5/6 invalid patches · FaultLine rejected 0/6</strong></span>
          </div>
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
            <button
              type="button"
              className="btn quiet"
              onClick={revertStore}
              disabled={running || busy !== null}
              title="Reset apps/buggyshop-backend/app/routes/checkout.py to seeded bug"
            >
              {busy === "revert" ? "Reverting…" : "Revert store to defect"}
            </button>
          </div>
          {gate && <p id="gate" className="gate" role="status">{gate}</p>}
          {notice && <p className="notice" data-tone={notice.tone} role="alert">{notice.text}</p>}
        </section>

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
                  <dd>{terminal ? `${((Date.parse(job.updated_at) - Date.parse(job.created_at)) / 1000).toFixed(1)} s` : elapsed !== null ? `${elapsed.toFixed(1)} s running` : "in progress"}</dd>
                </div>
                <div><dt>Event stream</dt><dd>{stream}</dd></div>
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
            {verified && (
              <div
                style={{
                  display: "flex",
                  gap: "12px",
                  alignItems: "center",
                  flexWrap: "wrap",
                  margin: "18px 0",
                  padding: "16px",
                  borderRadius: "8px",
                  background: "rgba(35, 134, 54, 0.12)",
                  border: "1px solid rgba(35, 134, 54, 0.35)",
                }}
              >
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => applyPatch(job.id)}
                  disabled={busy !== null}
                >
                  {busy === "apply" ? "Applying fix…" : "Apply fix to live store"}
                </button>
                <button
                  type="button"
                  className="btn quiet"
                  onClick={revertStore}
                  disabled={busy !== null}
                >
                  {busy === "revert" ? "Reverting…" : "Revert store to defect"}
                </button>
                <span className="muted" style={{ fontSize: "13px" }}>
                  Hot-reloads live BuggyShop on port 8000 with verified AST-contained patch.
                </span>
              </div>
            )}
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
