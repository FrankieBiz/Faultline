"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AgentGatePanel from "@/components/AgentGatePanel";
import CliGuide from "@/components/CliGuide";
import ConfirmButton from "@/components/ConfirmButton";
import CrawlerHud, { applyCrawlEvent, crawlFromCheck, crawlInFlight, startCrawl, type CrawlState, type MissionRepair } from "@/components/CrawlerHud";
import { STEP_LABELS, currentStep } from "@/components/Evidence";
import GuidedFlow, { type FlowRun, type StoreHunt } from "@/components/GuidedFlow";
import HeroArena from "@/components/HeroArena";
import InvariantPanel from "@/components/InvariantPanel";
import JobResult, { summarizeJob } from "@/components/JobResult";
import JudgeEvidence from "@/components/JudgeEvidence";
import PackPanel from "@/components/PackPanel";
import ProbeDialog, { type ProbeValues } from "@/components/ProbeDialog";
import ScenarioRail, { type RailStatus, type Selection } from "@/components/ScenarioRail";
import { playFailureAlarm, playResolutionChime, readSoundPreference, writeSoundPreference, type Cue } from "@/lib/audio-cues";
import {
  ApiError, CrawlInterrupted, REASON, TERMINAL, api, checkVerdict, crawl, limitsStatusLabel, providerName, providerNote, routeOf, sameOrigin,
  type CheckRecord, type Invariant, type Job, type JobDetail, type JobEvent, type Readiness,
  type RepairScenario, type ScenarioListing, type StoreStatus, type Tone,
} from "@/lib/faultline-api";

const POLL_MS = 1500;
/** Attempts against a crawler endpoint that is still starting before a direct check stands in. */
const CRAWL_ATTEMPTS = 3;
/** Attempts while a stopped crawl still holds the engine's one crawl slot; its browser can take seconds to close. */
const DRAIN_ATTEMPTS = 5;

type Stream = "idle" | "live" | "reconnecting" | "closed";
type Busy = "submit" | "cancel" | "reset" | "apply" | "revert" | "check" | "remove" | null;
/** A guided-flow step that spans several requests: revert then re-check, or apply then confirm. */
type FlowAction = "break" | "confirm" | null;

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Unexpected client error.");
const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
// Bring a fresh live check result into view without jumping when it is already visible.
const revealCheck = () => {
  const el = document.querySelector("#workspace .check");
  if (el) el.scrollIntoView({ block: "nearest", behavior: "auto" });
};
const revealHud = () => {
  const el = document.querySelector(".hud");
  if (el) el.scrollIntoView({ block: "nearest", behavior: "auto" });
};
/** What stands in for the crawler when its endpoint is not answering: a real HTTP check, named for the HUD. */
type CrawlFallback = { title: string; run: () => Promise<CheckRecord | null> };
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
  /** The URL the custom check dialog opens with, carried over from the header field. */
  const [dialogSeed, setDialogSeed] = useState("");
  const [quickTesting, setQuickTesting] = useState(false);
  const [crawlState, setCrawlState] = useState<CrawlState | null>(null);
  /** Which surface shows the crawl: the Mission HUD, the Pre-Flight Gate that launched it, or both once the gate hands it over. */
  const [crawlOrigin, setCrawlOrigin] = useState<"hud" | "gate" | "both">("hud");
  const crawlAbort = useRef<AbortController | null>(null);
  /** The sandbox run started for the defect the HUD shows, so the HUD follows only that repair. */
  const [missionJobId, setMissionJobId] = useState<string | null>(null);
  const [flowAction, setFlowAction] = useState<FlowAction>(null);
  /** Bumped to open the CLI guide; the dialog closes itself. */
  const [guideRequest, setGuideRequest] = useState(0);
  /** Bumped to open the judge evidence drawer. */
  const [judgeRequest, setJudgeRequest] = useState(0);
  const [sound, setSound] = useState(false);
  const soundRef = useRef(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  /** The job seen running in this session, so a cue marks a transition rather than a past record. */
  const watchedJob = useRef<string | null>(null);
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

  const cue = useCallback((name: Cue) => {
    if (!soundRef.current) return;
    if (name === "catastrophe") playFailureAlarm();
    else playResolutionChime();
  }, []);
  const toggleSound = () => {
    const next = !soundRef.current;
    soundRef.current = next;
    setSound(next);
    writeSoundPreference(next);
    // The click that enables sound is the gesture that unlocks audio; confirm with the pass cue.
    if (next) playResolutionChime();
  };

  // Read the stored preference after hydration, so server and client render the same first frame.
  useEffect(() => {
    const stored = readSoundPreference();
    soundRef.current = stored;
    setSound(stored);
  }, []);

  // A crawl streams until it finishes; leaving the page ends it.
  useEffect(() => () => crawlAbort.current?.abort(), []);

  // "?" opens the workflow quick sheet and "J" the judge evidence, from anywhere except a text field or an open dialog.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const open = event.key === "?" ? setGuideRequest : event.key === "j" || event.key === "J" ? setJudgeRequest : null;
      if (!open || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], dialog[open]")) return;
      event.preventDefault();
      open((n) => n + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
    /** A poll asked for while one is in flight runs as soon as that one settles. */
    let pollSoon = false;
    let lastStage: string | null = null;

    const stop = () => {
      stopped = true;
      source?.close();
      clearTimeout(pollTimer);
      clearTimeout(retryTimer);
    };

    const pollNow = (delay: number) => {
      if (stopped) return;
      if (polling) { pollSoon = true; return; }
      clearTimeout(pollTimer);
      pollTimer = setTimeout(poll, delay);
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
            pollNow(50);
          }
        } catch {}
      });
      // The server ends the stream once the job is terminal, which EventSource reports as an error.
      // Read the record first: a finished run then reads "closed" without flashing "reconnecting".
      source.onerror = () => {
        source?.close();
        if (stopped) return;
        pollNow(0);
        retryTimer = setTimeout(() => {
          setStream("reconnecting");
          open();
        }, Math.min(8000, 500 * 2 ** retries++));
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
      if (!stopped) pollTimer = setTimeout(poll, pollSoon ? 0 : POLL_MS);
      pollSoon = false;
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

  const { job, verified, outcome, verification } = summarizeJob(detail);
  const terminal = job ? TERMINAL.has(job.state) : false;

  // Cue once when a run watched in this session settles: resolution for a verified fix, alarm for a failure.
  useEffect(() => {
    if (!job) return;
    if (!terminal) { watchedJob.current = job.id; return; }
    if (watchedJob.current !== job.id) return;
    watchedJob.current = null;
    if (verified) cue("resolve");
    else if (outcome?.tone === "bad") cue("catastrophe");
  }, [job, terminal, verified, outcome, cue]);
  // Until the first record arrives the job is assumed active, unless the record cannot be read at all.
  const running = jobId !== null && (job ? !terminal : syncError === null);

  const status = readiness?.status;
  const gate =
    status === "ready" ? null
    : status === "detect_only"
      ? `The repair provider is unavailable (${readiness?.model?.reason ?? "no reason given"}). A detection run reproduces the failure without requesting a patch.`
    : status === "blocked" ? REASON[readiness?.reason ?? ""] ?? "Execution is blocked by the orchestrator."
    : readinessError ?? "Checking orchestrator readiness…";

  /** Resolves to the accepted job's id, or null when the orchestrator refused it. */
  const start = async (mode: "repair" | "detect", scenarioId: string): Promise<string | null> => {
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
      // A repair of the defect on the HUD, from either button, is the mission's repair.
      if (mode === "repair" && defectScenario?.id === scenarioId) setMissionJobId(accepted.job_id);
      return accepted.job_id;
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      void refreshReadiness();
      return null;
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

  const cueFor = (record: CheckRecord) => {
    const tone = checkVerdict(record).tone;
    if (tone === "bad") cue("catastrophe");
    else if (tone === "ok") cue("resolve");
  };

  /** `quiet` keeps the current notice and holds the cue, for checks that only wait out a store reload. */
  const runCheck = async (invariant: Invariant, port: number | null, quiet = false): Promise<CheckRecord | null> => {
    setBusy("check");
    setCheckingId(invariant.id);
    if (!quiet) setNotice(null);
    try {
      const record = await api<CheckRecord>(`invariants/${encodeURIComponent(invariant.id)}/check`, json(port ? { port } : {}));
      setChecks((current) => ({ ...current, [invariant.id]: [record, ...(current[invariant.id] ?? [])].slice(0, 10) }));
      if (!quiet) cueFor(record);
      void refreshListing();
      return record;
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      return null;
    } finally {
      setBusy(null);
      setCheckingId(null);
    }
  };

  /** Registration errors stay in the dialog; the live check and any repair follow once it closes. */
  const submitProbe = async (values: ProbeValues) => {
    const created = await api<Invariant>("invariants", json({
      title: values.title || undefined, method: values.method, url: values.url,
      expected_status: values.expectedStatus, ...(values.body !== undefined ? { body: values.body } : {}),
    }));
    setDialogOpen(false);
    setDialogSeed("");
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
      setNotice({ tone: "idle", text: `Removed "${invariant.title}" and its check history.` });
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  /** Resolves true once the store's source holds the fix. */
  const applyFix = async (): Promise<boolean> => {
    if (!job || !verified) return false;
    setBusy("apply");
    setNotice(null);
    try {
      const result = await api<{ store: StoreStatus }>(`jobs/${encodeURIComponent(job.id)}/apply`, { method: "POST" });
      setStore(result.store);
      setNotice({ tone: "ok", text: `Applied run ${job.id.slice(0, 8)}'s verified fix to ${result.store.target_file}. The store reloads in a moment; ${liveCheckout ? "checkout is checked live once it answers" : "check it live to confirm"}.` });
      return true;
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      void refreshStore();
      return false;
    } finally {
      setBusy(null);
    }
  };

  /** Resolves true once the store's source is back on the seeded defect. */
  const revertStore = async (): Promise<boolean> => {
    setBusy("revert");
    setNotice(null);
    try {
      const result = await api<{ store: StoreStatus }>("revert", { method: "POST" });
      setStore(result.store);
      setNotice({ tone: "warn", text: `Reverted ${result.store.target_file} to the seeded defect. Checkout without a coupon fails again.` });
      return true;
    } catch (e) {
      setNotice({ tone: "bad", text: errorText(e) });
      void refreshStore();
      return false;
    } finally {
      setBusy(null);
    }
  };

  /**
   * Check the store's checkout live and show the result. After a source change the store hot-reloads,
   * so `reloading` re-checks a few times until it reports the expected verdict; every check is recorded.
   */
  const settleLive = async (want: Tone, reloading: boolean): Promise<CheckRecord | null> => {
    if (!liveCheckout) return null;
    select({ kind: "invariant", id: liveCheckout.id });
    let record: CheckRecord | null = null;
    for (let attempt = 0; attempt < (reloading ? 5 : 1); attempt++) {
      if (reloading) await pause(1500);
      record = await runCheck(liveCheckout, liveCheckout.default_port, reloading);
      if (!record || checkVerdict(record).tone === want) break;
    }
    if (record && reloading) cueFor(record);
    revealCheck();
    return record;
  };

  /**
   * Stream a Playwright chaos crawl of `url` into the HUD. While the crawler endpoint is starting
   * (no answer, 502, 503) it is retried briefly; when it is still unavailable, or absent (404),
   * `fallback` sends a real HTTP check instead and the HUD shows that check's sessions, labeled as such.
   */
  const runCrawl = async (url: string, fallback: CrawlFallback | null, origin: "hud" | "gate" = "hud") => {
    crawlAbort.current?.abort();
    const controller = new AbortController();
    crawlAbort.current = controller;
    const update = (change: (state: CrawlState) => CrawlState) => {
      if (!controller.signal.aborted) setCrawlState((state) => state && change(state));
    };
    setCrawlState(startCrawl(url));
    setCrawlOrigin(origin);
    setMissionJobId(null);
    if (origin === "hud") revealHud();
    for (let attempt = 1; ; attempt++) {
      let seen = false;
      try {
        await crawl(url, (event) => {
          if (controller.signal.aborted) return;
          seen = true;
          if (event.type === "defect") cue("catastrophe");
          update((state) => applyCrawlEvent(state, event));
        }, controller.signal);
        update((state) => crawlInFlight(state) ? { ...state, phase: "incomplete", note: "The crawler stopped before reporting a result." } : state);
        return;
      } catch (e) {
        if (controller.signal.aborted) return;
        const starting = e instanceof ApiError && [0, 502, 503].includes(e.status);
        const absent = e instanceof ApiError && e.status === 404;
        // A crawl stopped a moment ago keeps the engine's one crawl slot until its browser exits.
        const draining = e instanceof ApiError && e.status === 409 && e.code === "crawl_in_progress";
        if (seen || e instanceof CrawlInterrupted || !(starting || absent || draining)) {
          update((state) => ({ ...state, phase: "failed", note: e instanceof Error && !(e instanceof ApiError) ? e.message : errorText(e) }));
          return;
        }
        if (draining) {
          if (attempt >= DRAIN_ATTEMPTS) {
            update((state) => ({ ...state, phase: "failed", note: errorText(e) }));
            return;
          }
          update((state) => ({ ...state, phase: "retrying", note: `The previous crawl is still closing its browser. Retrying (${attempt + 1} of ${DRAIN_ATTEMPTS})…` }));
          await pause(1000 * attempt);
          if (controller.signal.aborted) return;
          continue;
        }
        if (starting && attempt < CRAWL_ATTEMPTS) {
          update((state) => ({ ...state, phase: "retrying", note: `Crawler is starting up. Retrying (${attempt + 1} of ${CRAWL_ATTEMPTS})…` }));
          await pause(1000 * attempt);
          if (controller.signal.aborted) return;
          continue;
        }
        const why = absent ? "This engine has no Playwright crawler endpoint yet" : "The Playwright crawler is not answering";
        if (!fallback) {
          update((state) => ({ ...state, phase: "failed", note: `${why}, and no direct check covers this page.` }));
          return;
        }
        update((state) => ({ ...state, phase: "fallback", source: "check", note: null, fallbackReason: `${why}. Sending "${fallback.title}" directly from two fresh sessions instead.` }));
        try {
          const record = await fallback.run();
          update((state) => record ? crawlFromCheck(state, record, fallback.title)
            : { ...state, phase: "failed", note: "The direct check could not run. See the message in the workspace." });
        } catch (error) {
          update((state) => ({ ...state, phase: "failed", note: errorText(error) }));
        }
        return;
      }
    }
  };

  const closeCrawl = () => {
    crawlAbort.current?.abort();
    crawlAbort.current = null;
    setCrawlState(null);
    setMissionJobId(null);
  };

  /** The store's own checkout check, standing in for the crawler on the store's origins. */
  const storeFallback = (reloading: boolean): CrawlFallback | null =>
    liveCheckout ? { title: liveCheckout.title, run: () => settleLive("bad", reloading) } : null;

  // Step 1: crawl the store until checkout breaks, restoring the seeded defect first when a fix is applied.
  const breakStore = async () => {
    if (!store) return;
    setFlowAction("break");
    try {
      const seeded = store.state === "seeded";
      if (!seeded && !await revertStore()) return;
      // A reverted store hot-reloads; give it a moment before the crawler loads it.
      if (!seeded) await pause(1500);
      await runCrawl(storefrontUrl, storeFallback(!seeded));
    } finally {
      setFlowAction(null);
    }
  };

  // Step 2: the same sandbox repair as the scenario's own button.
  const repairStore = () => {
    if (!storePack) return;
    select({ kind: "pack", id: storePack.id });
    void start("repair", storePack.id);
  };

  // Step 3: write the verified fix, then wait for the reloaded store to pass the live check.
  const applyAndConfirm = async () => {
    if (!await applyFix() || !liveCheckout) return;
    setFlowAction("confirm");
    try {
      await settleLive("ok", true);
    } finally {
      setFlowAction(null);
    }
  };

  /** Hero ping: reuse the saved GET probe for this URL when there is one, then check it live. */
  const quickTest = async (url: string): Promise<CheckRecord | null> => {
    const existing = listing?.invariants.find((i) => i.source === "probe" && i.method === "GET" && i.url === url
      && i.expected_status === 200 && !i.has_body) ?? null;
    setQuickTesting(true);
    try {
      const target = existing ?? await api<Invariant>("invariants", json({ method: "GET", url, expected_status: 200 }));
      if (!existing) await refreshListing();
      select({ kind: "invariant", id: target.id });
      const record = await runCheck(target, null);
      if (record) revealCheck();
      return record;
    } finally {
      setQuickTesting(false);
    }
  };

  /** Hero crawl: on the store's origins the checkout check stands in for the crawler, elsewhere a GET ping. */
  const autoBreak = async (url: string, origin: "hud" | "gate" = "hud") => {
    const onStore = sameOrigin(url, storefrontUrl, null) || (store !== null && sameOrigin(url, store.url, null));
    await runCrawl(url, (onStore ? storeFallback(false) : null) ?? { title: `GET ${url}`, run: () => quickTest(url) }, origin);
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
  // The rail reports only the run on screen, with the same evidence test as its result heading.
  const packStatus: Record<string, RailStatus> = !job ? {}
    : { [job.scenario_id]: running ? { tone: "active", text: "sandbox run in progress…" }
      : verified ? { tone: "ok", text: "last run: verified repair" }
      : outcome ? { tone: outcome.tone, text: `last run: ${outcome.title.toLowerCase()}` }
      : { tone: "idle", text: "repairable in the sandbox" } };
  const readinessTone = status === "ready" ? "ok" : status === "detect_only" ? "warn"
    : status === "blocked" || readinessError ? "bad" : "active";
  const liveCheck = liveCheckout ? checks[liveCheckout.id]?.[0] ?? liveCheckout.latest_check : null;
  // The guided flow speaks only for the store's own repair; another scenario's run leaves it idle.
  const storeJob = job && storePack && job.scenario_id === storePack.id ? job : null;
  const model = readiness?.model ?? null;
  const metaReady = model?.provider === "meta" && model.available;
  const passedChecks = verification?.report.assertions.filter((a) => a.passed).length ?? 0;
  const flowRun: FlowRun = {
    label: metaReady ? "Repair with Meta" : `Auto-repair (${model?.model || "deterministic-checkout-v1"})`,
    source: !model ? "Runs in an isolated Bubblewrap sandbox"
      : metaReady ? `${model.model} in a Bubblewrap sandbox` : providerNote(model.provider) ?? providerName(model.provider, model.model),
    running: storeJob !== null && running,
    stage: storeJob && running ? STEP_LABELS[currentStep(storeJob, events)] ?? null : null,
    verified: storeJob !== null && verified,
    checks: storeJob && verified && verification ? { passed: passedChecks, total: verification.report.assertions.length } : null,
    outcome: storeJob && !running && !verified && outcome ? outcome : null,
    blocked: status === "ready" ? null : status === "detect_only" ? "Repair provider unavailable"
      : status === "blocked" || readinessError ? "Engine needs attention" : "Checking the engine…",
  };
  const crawlRunning = crawlInFlight(crawlState);
  const crawlDefect = crawlState?.defect ?? null;
  const defectRoute = crawlDefect ? `${crawlDefect.method.toUpperCase()} ${crawlDefect.path}` : null;
  const defectScenario = crawlDefect
    ? listing?.scenarios.find((s) => s.id === crawlDefect.scenario_id) ?? listing?.scenarios.find((s) => s.route && s.route === defectRoute) ?? null
    : null;
  const crawlRepairBlocked = !crawlDefect ? null
    : !defectScenario ? `No sandbox repair covers ${defectRoute} yet, so this failure is detection only.`
    : running ? "A sandbox run is in progress."
    : flowRun.blocked ?? (busy !== null || flowAction !== null || crawlRunning ? "Waiting for the current action to finish…" : null);
  const repairLabel = !metaReady ? "Auto-repair"
    : model.model.toLowerCase().includes("muse-spark") ? "Repair with Meta Muse Spark" : "Repair with Meta";
  // Step 1 counts a crawl only when it ran against the store and caught the store's own route failing.
  const onStoreCrawl = crawlState !== null && (sameOrigin(crawlState.target, storefrontUrl, null) || (store !== null && sameOrigin(crawlState.target, store.url, null)));
  const hunt: StoreHunt = {
    running: onStoreCrawl && crawlState !== null && ["connecting", "retrying", "running"].includes(crawlState.phase),
    caughtOn: onStoreCrawl && crawlState?.source === "playwright" && crawlDefect && storeRoute !== null && defectRoute === storeRoute
      ? crawlDefect.trigger.page : null,
  };
  const repairFromCrawl = () => {
    if (!defectScenario) return;
    select({ kind: "pack", id: defectScenario.id });
    void start("repair", defectScenario.id);
  };
  // The HUD follows the mission's own run through verification and delivery, never another record.
  const missionJob = job && job.id === missionJobId ? job : null;
  const missionDelivers = missionJob !== null && storePack !== null && missionJob.scenario_id === storePack.id;
  const limits = verification?.resource_limits;
  const missionRepair: MissionRepair | null = !missionJob ? null : {
    running,
    stage: running ? STEP_LABELS[currentStep(missionJob, events)] ?? null : null,
    verified,
    checks: verified && verification ? { passed: passedChecks, total: verification.report.assertions.length } : null,
    sandbox: limits?.verified && limits.mode === "cgroup-v2-scope" ? "the Bubblewrap sandbox under cgroup v2 limits" : "the Bubblewrap sandbox",
    outcome: !running && !verified ? outcome : null,
    canApply: missionDelivers && verified && store?.state === "seeded" && busy === null && flowAction === null && !crawlRunning,
    applyNote: missionDelivers ? null : "Project repairs stay in the sandbox; FaultLine never writes your working source. Review the diff below.",
    applying: missionDelivers && (busy === "apply" || flowAction === "confirm"),
    applied: missionDelivers && store?.state === "patched" && store.applied_job_id === missionJob.id ? {
      file: store.target_file,
      live: liveCheck && flowAction !== "confirm" ? (() => {
        const verdict = checkVerdict(liveCheck);
        const code = liveCheck.sessions.find((s) => s.status !== null)?.status;
        return { tone: verdict.tone, text: verdict.tone === "ok" ? `Live checkout re-checked: HTTP ${code} · defect gone.` : `Live checkout: ${verdict.title}.` };
      })() : null,
    } : null,
  };
  const repairCore = model
    ? { tone: metaReady ? "ok" as const : "warn" as const,
      text: model.provider === "meta" && !model.available ? `${providerName(model.provider, model.model)} · unavailable` : providerName(model.provider, model.model) }
    : { tone: readinessError ? "bad" as const : "idle" as const, text: readinessError ? "Engine unreachable" : "Checking the engine…" };
  const engineLabel = status === "ready" ? "Ready" : status === "detect_only" ? "Detection only"
    : status === "blocked" || readinessError ? "Needs attention" : "Checking…";

  return (
    <>
      <a className="skip" href="#workspace">Skip to the selected scenario</a>
      <a className="skip" href="#demo">Skip to the guided demo</a>
      <header className="top">
        <div className="shell top-row">
          <span className="wordmark"><span aria-hidden="true" className="glyph" />FaultLine{" "}<span className="wordmark-sub">Inspector</span></span>
          <div className="top-tools">
            <span className="readiness" data-tone={readinessTone}>
              <span className="readiness-dot" aria-hidden="true" />
              <span className="readiness-key">Engine Status:</span> {engineLabel}
            </span>
            <button type="button" className="btn tool judge-open" onClick={() => setJudgeRequest((n) => n + 1)} aria-keyshortcuts="J" aria-haspopup="dialog">
              <span className="judge-mark" aria-hidden="true" />Judge evidence <kbd aria-hidden="true">J</kbd>
            </button>
            <a className="btn quiet tool gate-link" href="#gate"><span className="gate-lock" aria-hidden="true" />Pre-Flight Gate</a>
            <button type="button" className="btn quiet tool" onClick={() => setGuideRequest((n) => n + 1)} aria-keyshortcuts="?" aria-haspopup="dialog">
              CLI guide <kbd aria-hidden="true">?</kbd>
            </button>
            <button type="button" className="btn quiet tool" onClick={toggleSound} aria-pressed={sound}>
              <span className="sound-mark" data-on={sound} aria-hidden="true" />Sound cues
            </button>
          </div>
        </div>
      </header>
      {/* One reading order for the demo: what it is, the guided path, its live evidence, the deploy gate, then every scenario. */}
      <main>
        <HeroArena storefrontUrl={storefrontUrl} apiUrl={store?.url ?? null}
          busy={busy !== null || quickTesting || flowAction !== null || crawlRunning}
          hunting={crawlRunning && flowAction === null && crawlOrigin !== "gate"} pinging={quickTesting && !crawlRunning}
          onHunt={autoBreak} onPing={async (url) => { await quickTest(url); }} repairCore={repairCore} engineTone={readinessTone} />
        {(storePack || !listing) && <GuidedFlow store={store} error={storeError} storefrontUrl={storefrontUrl}
          liveCheck={liveCheck} canCheckLive={liveCheckout !== null} run={flowRun} hunt={hunt}
          verifiedJobId={verified && job ? job.id : null}
          busy={busy !== null || running || flowAction !== null || quickTesting || crawlRunning}
          breaking={flowAction === "break"} applying={busy === "apply"} confirming={flowAction === "confirm"}
          reverting={busy === "revert"} checking={liveCheckout !== null && checkingId === liveCheckout.id}
          onBreak={() => void breakStore()} onRepair={repairStore} onApply={() => void applyAndConfirm()}
          onRevert={() => void revertStore()} onRetry={refreshStore} onCheckLive={() => void settleLive("bad", false)} />}
        {crawlState && crawlOrigin !== "gate" && <CrawlerHud state={crawlState} repairLabel={repairLabel} repairBlocked={crawlRepairBlocked}
          repair={missionRepair} onRepair={repairFromCrawl} onApply={() => void applyAndConfirm()} onDismiss={closeCrawl} />}
        <AgentGatePanel state={crawlOrigin !== "hud" ? crawlState : null} missionOpen={crawlOrigin === "both"} storefrontUrl={storefrontUrl} storeState={store?.state ?? null}
          busy={busy !== null || quickTesting || flowAction !== null || crawlRunning}
          onRun={(url) => autoBreak(url, "gate")} onOpenMission={() => { setCrawlOrigin("both"); revealHud(); }} onReset={closeCrawl} />

        <div className="shell dashboard">
          <ScenarioRail listing={listing} error={listingError} selection={selection} packStatus={packStatus} checkingId={checkingId}
            onSelect={select} onNew={() => { setDialogSeed(""); setDialogOpen(true); }} onRetry={refreshListing} />
          <section id="workspace" tabIndex={-1} aria-label="Selected scenario">
            {/* Failures interrupt; confirmations wait their turn, so a guided step never stacks alerts. */}
            {notice && <p className="notice" data-tone={notice.tone} role={notice.tone === "bad" || notice.tone === "warn" ? "alert" : "status"}>{notice.text}</p>}
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
              <p className="empty">Choose a scenario, or test any URL from the bar above.</p>
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
              <ConfirmButton className="btn" disabled={running || busy !== null || !readiness} confirmLabel="Confirm reset?" onConfirm={() => void reset()}>
                {busy === "reset" ? "Resetting…" : "Reset environment"}
              </ConfirmButton>{" "}
              <button type="button" className="btn quiet" onClick={refreshReadiness} disabled={busy !== null}>Refresh readiness</button>
            </details>
          </section>
        </div>
      </main>
      <CliGuide request={guideRequest} />
      <JudgeEvidence request={judgeRequest} readiness={readiness} readinessError={readinessError} />
      <ProbeDialog open={dialogOpen} seedUrl={dialogSeed} storeUrl={store?.url ?? null} onClose={() => setDialogOpen(false)} onSubmit={submitProbe} />
      <footer className="shell foot"><span>FaultLine · verified repair runs locally; nothing is pushed or deployed.</span><a href="https://github.com/FrankieBiz/Faultline">Source</a></footer>
    </>
  );
}
