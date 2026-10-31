"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import InvariantPanel from "@/components/InvariantPanel";
import JobResult, { summarizeJob } from "@/components/JobResult";
import PackPanel from "@/components/PackPanel";
import ProbeDialog, { type ProbeValues } from "@/components/ProbeDialog";
import ScenarioRail, { type Selection } from "@/components/ScenarioRail";
import StoreBar from "@/components/StoreBar";
import {
  ApiError, REASON, TERMINAL, api, limitsStatusLabel, providerName, routeOf, sameOrigin,
  type CheckRecord, type Invariant, type Job, type JobDetail, type JobEvent, type Readiness,
  type RepairScenario, type ScenarioListing, type StoreStatus, type Tone,
} from "@/lib/faultline-api";

const POLL_MS = 1500;

type Stream = "idle" | "live" | "reconnecting" | "closed";
type Busy = "submit" | "cancel" | "reset" | "apply" | "revert" | "check" | "remove" | null;

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Unexpected client error.");
const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
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
  const [listing, setListing] = useState<ScenarioListing | null>(null);
  const [listingError, setListingError] = useState<string | null>(null);
  const [store, setStore] = useState<StoreStatus | null>(null);
  const [storeError, setStoreError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [checks, setChecks] = useState<Record<string, CheckRecord[]>>({});
  const [checksError, setChecksError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
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

  const refreshListing = useCallback(async () => {
    try {
      const next = await api<ScenarioListing>("scenarios");
      setListing(next);
      setListingError(null);
      // Keep the operator's selection; default to the first repairable scenario.
      setSelection((current) => current
        ?? (next.scenarios[0] ? { kind: "pack", id: next.scenarios[0].id }
          : next.invariants[0] ? { kind: "invariant", id: next.invariants[0].id } : null));
      return next;
    } catch (e) {
      setListingError(errorText(e));
      return null;
    }
  }, []);

  const refreshStore = useCallback(async () => {
    try {
      setStore(await api<StoreStatus>("store"));
      setStoreError(null);
    } catch (e) {
      setStore(null);
      setStoreError(errorText(e));
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
    void refreshListing();
    void refreshStore();
    refreshHistory()
      .then((jobs) => { if (live && jobs[0] && !TERMINAL.has(jobs[0].state)) follow(jobs[0].id); })
      .catch((e) => { if (live) setNotice({ tone: "bad", text: errorText(e) }); })
      .finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [refreshReadiness, refreshListing, refreshStore, refreshHistory, follow]);

  // Every recorded check of the selected invariant, newest first.
  const selectedInvariant = selection?.kind === "invariant" ? selection.id : null;
  useEffect(() => {
    if (!selectedInvariant) return;
    let live = true;
    setChecksError(null);
    api<{ checks: CheckRecord[] }>(`invariants/${encodeURIComponent(selectedInvariant)}/checks?limit=10`)
      .then(({ checks: list }) => { if (live) setChecks((current) => ({ ...current, [selectedInvariant]: list })); })
      .catch((e) => { if (live) setChecksError(errorText(e)); });
    return () => { live = false; };
  }, [selectedInvariant]);

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

  const { job, verified } = summarizeJob(detail);
  const terminal = job ? TERMINAL.has(job.state) : false;
  // Until the first record arrives the job is assumed active, unless the record cannot be read at all.
  const running = jobId !== null && (job ? !terminal : syncError === null);

  const status = readiness?.status;
  const gate =
    status === "ready" ? null
    : status === "detect_only"
      ? `The repair provider is unavailable (${readiness?.model?.reason ?? "no reason given"}). A detection run reproduces the failure without requesting a patch.`
    : status === "blocked" ? REASON[readiness?.reason ?? ""] ?? "Execution is blocked by the orchestrator."
    : readinessError ?? "Checking orchestrator readiness…";

  const start = async (mode: "repair" | "detect", scenarioId: string) => {
    setBusy("submit");
    setNotice(null);
    try {
      const accepted = await api<{ job_id: string; effective_mode: string; repair_block_reason: string | null }>(
        "jobs", json({ scenario_id: scenarioId, idempotency_key: newKey(), mode }),
      );
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

  const runCheck = async (invariant: Invariant, port: number | null): Promise<CheckRecord | null> => {
    setBusy("check");
    setNotice(null);
    try {
      const record = await api<CheckRecord>(`invariants/${encodeURIComponent(invariant.id)}/check`, json(port ? { port } : {}));
      setChecks((current) => ({ ...current, [invariant.id]: [record, ...(current[invariant.id] ?? [])].slice(0, 10) }));
      void refreshListing();
      return record;
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      return null;
    } finally {
      setBusy(null);
    }
  };

  /** Registration errors stay in the dialog; the live check and any repair follow once it closes. */
  const submitProbe = async (values: ProbeValues) => {
    const created = await api<Invariant>("invariants", json({
      title: values.title || undefined, method: values.method, url: values.url,
      expected_status: values.expectedStatus, ...(values.body !== undefined ? { body: values.body } : {}),
    }));
    setDialogOpen(false);
    setSelection({ kind: "invariant", id: created.id });
    void (async () => {
      await refreshListing();
      const record = await runCheck(created, null);
      if (!record || !values.autoRepair || record.outcome !== "detected" || !record.repair) return;
      if (status !== "ready") {
        setNotice({ tone: "warn", text: `Reproduced live, but the sandbox repair cannot start: ${gate}` });
        return;
      }
      await start("repair", record.repair.scenario_id);
    })();
  };

  const removeProbe = async (invariant: Invariant) => {
    setBusy("remove");
    setNotice(null);
    try {
      await api(`invariants/${encodeURIComponent(invariant.id)}/remove`, { method: "POST" });
      const next = await refreshListing();
      setSelection(next?.scenarios[0] ? { kind: "pack", id: next.scenarios[0].id } : null);
      setNotice({ tone: "idle", text: `Removed the probe "${invariant.title}" and its check history.` });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  const applyFix = async () => {
    if (!job || !verified) return;
    setBusy("apply");
    setNotice(null);
    try {
      const result = await api<{ store: StoreStatus }>(`jobs/${encodeURIComponent(job.id)}/apply`, { method: "POST" });
      setStore(result.store);
      setNotice({ tone: "ok", text: `Applied run ${job.id.slice(0, 8)}'s verified fix to ${result.store.target_file}. The store reloads in a moment; check it live to confirm.` });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      void refreshStore();
    } finally {
      setBusy(null);
    }
  };

  const revertStore = async () => {
    setBusy("revert");
    setNotice(null);
    try {
      const result = await api<{ store: StoreStatus }>("revert", { method: "POST" });
      setStore(result.store);
      setNotice({ tone: "warn", text: `Reverted ${result.store.target_file} to the seeded defect. Checkout without a coupon fails again.` });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      void refreshStore();
    } finally {
      setBusy(null);
    }
  };

  const select = (next: Selection) => {
    setSelection(next);
    setChecksError(null);
    document.getElementById("workspace")?.focus({ preventScroll: true });
  };

  const pack = selection?.kind === "pack" ? listing?.scenarios.find((s) => s.id === selection.id) ?? null : null;
  const invariant = selection?.kind === "invariant" ? listing?.invariants.find((i) => i.id === selection.id) ?? null : null;
  const routeCovers = (i: Invariant, route: string) => routeOf(i.method, i.url) === route;
  // A pack covers live checks on its route; a project scenario covers its own faultline.toml entry.
  const covers = (i: Invariant, s: RepairScenario) => s.route ? routeCovers(i, s.route) : i.id === `scenario.${s.id}`;
  // Delivery exists only for the built-in store pipeline; project runs never touch working source.
  const storePack = listing?.scenarios.find((s) => (s.executor ?? "checkout") === "checkout" && s.route) ?? null;
  const storeRoute = storePack?.route ?? null;
  const liveCheckout = storeRoute && store
    ? listing?.invariants.find((i) => routeCovers(i, storeRoute) && sameOrigin(i.url, store.url, i.default_port)) ?? null
    : null;
  const repairGate = status === "ready" ? (running ? "A sandbox run is in progress. Wait for it to finish." : null) : gate;
  const jobScenario = job ? listing?.scenarios.find((s) => s.id === job.scenario_id)?.title ?? job.scenario_id : null;

  return (
    <>
      <a className="skip" href="#workspace">Skip to the selected scenario</a>
      <header className="top">
        <div className="shell top-row">
          <span className="wordmark"><span aria-hidden="true" className="glyph" />FaultLine</span>
          <span className="readiness" data-tone={status === "ready" ? "ok" : status === "detect_only" ? "warn" : "idle"}>
            {status === "ready" ? "Sandbox ready" : status === "detect_only" ? "Detection only" : status === "blocked" || readinessError ? "Sandbox needs attention" : "Checking sandbox…"}
          </span>
        </div>
      </header>
      {(storePack || !listing) && <StoreBar store={store} error={storeError} storefrontUrl={storefrontUrl}
        verifiedJobId={verified && job ? job.id : null}
        busy={busy !== null || running} applying={busy === "apply"} reverting={busy === "revert"} checking={busy === "check"}
        onApply={applyFix} onRevert={revertStore} onRetry={refreshStore}
        onCheckLive={liveCheckout ? () => { select({ kind: "invariant", id: liveCheckout.id }); void runCheck(liveCheckout, liveCheckout.default_port); } : null} />}

      <div className="shell dashboard">
        <ScenarioRail listing={listing} error={listingError} selection={selection}
          onSelect={select} onNew={() => setDialogOpen(true)} onRetry={refreshListing} />
        <main id="workspace" tabIndex={-1}>
          {notice && <p className="notice" data-tone={notice.tone} role="alert">{notice.text}</p>}
          {pack ? (
            <PackPanel scenario={pack} covering={listing?.invariants.filter((i) => covers(i, pack)) ?? []}
              readiness={readiness} readinessError={readinessError} gate={gate}
              running={running} busy={busy !== null} submitting={busy === "submit"} cancelling={busy === "cancel"}
              cancelRequested={Boolean(job?.cancel_requested)}
              onRun={(mode) => start(mode, pack.id)} onCancel={running && job ? cancel : null} onRetry={refreshReadiness}
              onSelect={select} />
          ) : invariant ? (
            <InvariantPanel key={invariant.id} invariant={invariant} checks={checks[invariant.id]} checksError={checksError}
              checking={busy === "check"} busy={busy !== null}
              canRepair={status === "ready" && !running && busy === null} repairGate={repairGate} repairing={busy === "submit"}
              onCheck={(port) => void runCheck(invariant, port)} onRepair={(id) => void start("repair", id)}
              onRemove={() => void removeProbe(invariant)} />
          ) : listing ? (
            <p className="empty">Choose a scenario, or add a new invariant to probe any URL.</p>
          ) : (
            <p className="empty" role="status">{listingError ?? "Loading scenarios…"}</p>
          )}

          {!loaded ? <p className="empty" role="status">Checking for an active run…</p>
          : !jobId ? null
          : !job || !detail ? <p className="empty" role="status">{syncError ?? "Starting the sandbox run…"}</p>
          : <JobResult detail={detail} events={events} stream={stream} running={running} pastRun={pastRun}
              syncError={syncError} scenarioTitle={jobScenario} resultRef={resultRef} headingRef={headingRef} />}

          <details className="history block">
            <summary>Past sandbox runs · {history.length} recent {history.length === 1 ? "run" : "runs"}</summary>
            {historyError && <p role="status">{historyError}</p>}
            {history.length === 0 ? <p className="muted">No sandbox runs yet.</p> : <ul className="rows">
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
        </main>
      </div>
      <ProbeDialog open={dialogOpen} storeUrl={store?.url ?? null} onClose={() => setDialogOpen(false)} onSubmit={submitProbe} />
      <footer className="shell foot"><span>FaultLine · verified repair runs locally; nothing is pushed or deployed.</span><a href="https://github.com/FrankieBiz/Faultline">Source</a></footer>
    </>
  );
}
