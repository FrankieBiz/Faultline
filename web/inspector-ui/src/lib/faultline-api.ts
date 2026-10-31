/**
 * Wire types and client helpers for the inspector proxy. Shapes mirror
 * shared/contracts/models.py and services/repair-orchestrator/app/main.py.
 */

export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
export type JobStage =
  | "preparing" | "baseline" | "diagnosing" | "patch_validation"
  | "activating" | "verification" | "cleanup" | "completed";
export type Outcome =
  | "verified" | "detected" | "no_failure" | "repair_unavailable" | "unexpected_failure"
  | "invalid_patch" | "model_error" | "unresolved" | "infrastructure_error"
  | "artifact_error" | "timeout" | "cleanup_failed" | "cancelled" | "interrupted";
export type Tone = "ok" | "bad" | "warn" | "idle";

export const TERMINAL: ReadonlySet<JobState> = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
export const STAGE_LABEL: Record<JobStage, string> = {
  preparing: "Prepare", baseline: "Reproduce", diagnosing: "Propose patch", patch_validation: "Policy check",
  activating: "Activate candidate", verification: "Verify", cleanup: "Clean up", completed: "Done",
};
export const STAGES = Object.keys(STAGE_LABEL) as JobStage[];

/** `ProbeResult` from app/model_adapter.py, serialized with dataclasses.asdict. */
export interface Probe { available: boolean; provider: string; model: string; reason: string | null }
/** `ResourceLimits` from shared/contracts/models.py: kernel read-back or explicit opt-out. */
export interface ResourceLimits {
  mode: "cgroup-v2-scope" | "disabled";
  memory_max_bytes: number | null;
  memory_swap_max_bytes: number | null;
  tasks_max: number | null;
  cpu_quota_percent: number | null;
  verified: boolean;
}
export interface LimitsStatus {
  requested: "required" | "disabled" | "invalid";
  mode: ResourceLimits["mode"] | null;
  configured: { memory_max_bytes: number; tasks_max: number; cpu_quota_percent: number } | null;
  enforcement_preflight: string | null;
  reason: string | null;
}
export interface Readiness {
  status: "ready" | "detect_only" | "blocked";
  runtime_ready: boolean;
  quarantined: boolean;
  model: Probe | null;
  reason: string | null;
  resource_limits?: LimitsStatus | null;
}

export interface Job {
  id: string;
  scenario_id: string;
  state: JobState;
  stage: JobStage;
  outcome: Outcome | null;
  cleanup_status: "not_started" | "in_progress" | "succeeded" | "failed";
  created_at: string;
  updated_at: string;
  error_details: Record<string, unknown> | null;
  requested_mode: "repair" | "detect";
  effective_mode: "repair" | "detect";
  repair_block_reason: string | null;
  cancel_requested: boolean;
}

export interface JobEvent { sequence: number; timestamp: string; stage: JobStage; message_code: string; message: string }

export interface Execution {
  runtime_kind?: "unverified" | "isolated-browser";
  resource_limits?: ResourceLimits | null;
  phase: "baseline" | "verification";
  attempt_id: string | null;
  candidate_snapshot_sha256: string;
  artifact_ids: string[];
  report: {
    execution_id: string;
    verdict: "passed" | "failed" | "error" | "timed_out";
    duration_ms: number;
    observations: { id: string; kind: string; message: string; source?: string; data?: Record<string, unknown> | null }[];
    assertions: { id: string; passed: boolean; expected: string; observed: string }[];
  };
}

export interface Attempt {
  id: string;
  attempt_number: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  raw_patch: string | null;
  parsed_diff: string | null;
  validation_result: Record<string, unknown> | null;
  outcome: string | null;
}

export interface Artifact {
  id: string; execution_id: string | null; attempt_id: string | null;
  role: string; content_type: string; size_bytes: number; sha256: string;
}

export interface JobDetail {
  job: Job; baseline: Execution | null; attempts: Attempt[];
  executions: Execution[]; artifacts: Artifact[]; events: JobEvent[];
}

/** `Scenario` from shared/config/scenarios.py: a repair the sandbox can rebuild and verify. */
export interface RepairScenario {
  id: string; title: string; description: string; target_file: string;
  route: string; error_fingerprint: string; expected_assertions: string[];
  /** "checkout" for the built-in store pipeline, "repro" for a project runner scenario. */
  executor?: string; regression_assertions?: string[];
}

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD" | "OPTIONS";
export const METHODS: Method[] = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];

/** `AssertionCheck` from app/repro.py: exactly one matcher, serialized only when set. */
export interface BodyCheck {
  path?: string; equals?: unknown; equals_path?: string; matches?: string; type?: string; exists?: boolean;
}

/** `CheckedAssertion`, `SessionResult`, and `CheckRecord` from app/probes.py. */
export interface CheckedAssertion { id: string; label: string; passed: boolean; expected: string; observed: string }
export interface SessionResult {
  session_id: string; status: number | null; duration_ms: number | null; content_type: string | null;
  excerpt: string | null; truncated: boolean; fingerprint: string | null; error: string | null;
  assertions: CheckedAssertion[];
  requests: { step_id: string; method: Method; path: string; status: number; duration_ms: number }[];
}
export interface CheckRecord {
  id: string; invariant_id: string; created_at: string; method: Method; url: string;
  outcome: "detected" | "no_failure" | "infrastructure_error"; reason: string;
  sessions: SessionResult[];
  repair: { scenario_id: string; title: string; target_file: string } | null;
  repair_note: string | null;
}

/** One ReproSpec step from app/repro.py, as serialized (absent keys were never set). */
export interface ReproStepWire {
  id: string; action: string; method?: Method; path?: string; body?: unknown; source?: string; check?: BodyCheck & { status?: number };
}

/** A live HTTP check: a faultline.toml scenario or rule, or a probe registered here. */
export interface Invariant {
  id: string; source: "config" | "probe" | "scenario"; title: string; description: string | null;
  method: Method; url: string; expected_status: number | null;
  has_body: boolean; body: unknown; assertions: BodyCheck[]; fingerprint: string | null;
  created_at: string | null; needs_port: boolean; default_port: number | null;
  latest_check: CheckRecord | null;
  /** The full ReproSpec of a faultline.toml scenario; null for rules and probes. */
  repro: { id: string; steps: ReproStepWire[] } | null;
  /** Why this entry cannot be checked live (browser steps run only in the sandbox). */
  live_note: string | null;
}

export interface ScenarioListing {
  scenarios: RepairScenario[];
  invariants: Invariant[];
  project: { name: string | null; config_path: string | null; errors: string[] };
}

/** app/live_store.py: what the locally running store serves right now. */
export interface StoreStatus {
  state: "seeded" | "patched" | "modified" | "missing";
  target_file: string; sha256: string | null; url: string;
  applied_job_id: string | null; applied_at: string | null;
}

/** How a live check reads to an operator; every branch comes from the recorded sessions. */
export function checkVerdict(check: CheckRecord): { tone: Tone; title: string; detail: string } {
  if (check.outcome === "detected") {
    return { tone: "bad", title: "Failing", detail: "Both fresh sessions failed the same way, so the failure reproduces." };
  }
  if (check.outcome === "infrastructure_error") {
    const error = check.sessions.find((s) => s.error)?.error;
    return {
      tone: "warn", title: "Check did not complete",
      detail: error === "ConnectError" ? `Nothing answered at ${new URL(check.url).origin}. Start the service, then check again.`
        : error ? `The request failed before a response was judged (${error}).` : "The check could not run both sessions.",
    };
  }
  if (check.reason === "nondeterministic_failure") {
    return { tone: "warn", title: "Failed differently each time", detail: "The two sessions disagreed, so this does not count as a reproduction." };
  }
  if (check.reason === "fingerprint_mismatch") {
    return { tone: "warn", title: "Different failure than declared", detail: "The server error did not match the rule's fingerprint." };
  }
  if (check.sessions.some((s) => s.assertions.some((a) => !a.passed))) {
    return { tone: "warn", title: "Intermittent", detail: "Only one of the two sessions failed, so this does not count as a reproduction." };
  }
  return { tone: "ok", title: "Passing", detail: "Both fresh sessions met every expectation." };
}

/** Whether an invariant targets the given origin; {port} resolves to the controller's default. */
export function sameOrigin(url: string, origin: string, port: number | null): boolean {
  if (url.includes("{port}") && port === null) return false;
  const host = (name: string) => (["127.0.0.1", "localhost", "[::1]"].includes(name) ? "loopback" : name);
  try {
    const a = new URL(url.replaceAll("{port}", String(port)));
    const b = new URL(origin);
    return a.protocol === b.protocol && host(a.hostname) === host(b.hostname) && a.port === b.port;
  } catch {
    return false;
  }
}

/** "POST /api/checkout": the route a registered repair scenario covers, if parseable. */
export function routeOf(method: string, url: string): string | null {
  try {
    return `${method} ${new URL(url.replaceAll("{port}", "1")).pathname}`;
  } catch {
    return null;
  }
}

/** Server error codes and readiness reasons, phrased for an operator. */
export const REASON: Record<string, string> = {
  isolated_runtime_unavailable:
    "No isolated runtime is configured, so the orchestrator refuses to execute checkout code. Runs stay disabled until containment exists.",
  aggregate_limits_unavailable:
    "Aggregate cgroup limits are required but unavailable, so candidate code will not run. Start the controller inside a systemd user session.",
  aggregate_limits_not_enforced:
    "The aggregate-limit probe did not observe enforcement, so candidate code will not run.",
  aggregate_limits_mode_invalid: "FAULTLINE_AGGREGATE_LIMITS must be required or disabled.",
  cleanup_required: "A previous job left resources quarantined. Reset the environment to reconcile them.",
  busy: "Another job holds the runtime lease. Wait for it to finish or cancel it.",
  unauthorized: "The orchestrator rejected the inspector's control token.",
  forbidden: "Same-origin or local network request required.",
  http_403: "Access forbidden. Ensure you are accessing FaultLine directly.",
  apply_failed: "Failed to apply verified patch to live codebase.",
  revert_failed: "Failed to revert live codebase to seeded defect.",
  unverified_job: "Safety policy: Only patches that passed 100% of sandbox assertions can be applied.",
  proxy_unreachable: "The orchestrator is not reachable through the inspector proxy.",
  reset_failed: "Reset could not reconcile owned resources. Check the orchestrator log.",
  not_found: "That record no longer exists in the orchestrator database.",
  store_not_seeded: "The live store is not on the seeded source. Revert it before applying a fix verified against the seed.",
  patch_apply_failed: "The verified diff did not apply to the live source. Revert the store and try again.",
  port_required: "This rule's URL uses {port}. Enter the port the service listens on.",
  too_many_probes: "You have 50 probes. Remove one before adding another.",
  config_invariant: "This rule lives in faultline.toml. Edit the file to change or remove it.",
  invalid_request: "The controller rejected the request as malformed.",
  delivery_unsupported: "Apply fix delivers only the showcase store's fix. Project runs leave your working source unchanged; apply their diff yourself.",
};

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message?: string) {
    super(REASON[code] ?? message ?? `Request failed: ${code.replaceAll("_", " ")} (HTTP ${status}).`);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/faultline/${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "proxy_unreachable");
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.ok) return body as T;
  const error = (body as { error?: unknown } | null)?.error;
  const message =
    error && typeof error === "object" && "message" in error && typeof error.message === "string"
      ? error.message.slice(0, 500)
      : undefined;
  const code =
    error && typeof error === "object" && "code" in error ? String(error.code)
    : response.status === 502 ? "proxy_unreachable" : `http_${response.status}`;
  throw new ApiError(response.status, code, message);
}

/** Identity is derived server-side from the endpoint host; only Meta hosts read as Meta. */
export function providerName(provider: string, model: string): string {
  if (provider === "deterministic") return `Deterministic fallback · ${model} · no model call`;
  if (provider === "meta") return `Meta Model API · ${model}`;
  if (provider === "local") return `Local model endpoint · ${model} · not a Meta-hosted call`;
  if (provider === "openai-compatible") return `OpenAI-compatible endpoint · ${model} · not a Meta-hosted call`;
  return `${provider} · ${model}`;
}

/** Plain-language caveat shown next to any provider that is not the Meta Model API. */
export function providerNote(provider: string): string | null {
  if (provider === "deterministic") return "Preset fix for local verification; not a Meta model trial.";
  if (provider === "meta") return null;
  return "Not a Meta model trial.";
}

export function providerLabel(probe: Probe | null): string {
  if (!probe) return "Not probed";
  const name = providerName(probe.provider, probe.model);
  return probe.available ? name : `${name} · unavailable (${probe.reason ?? "no reason given"})`;
}

const mib = (bytes: number) => `${Math.round(bytes / 1048576)} MiB`;

/** One line for an execution's recorded aggregate limits; absent records say so. */
export function limitsName(limits: ResourceLimits | null | undefined): string {
  if (!limits) return "aggregate limits not recorded";
  if (limits.mode === "disabled") return "aggregate limits disabled";
  return `cgroup ${mib(limits.memory_max_bytes ?? 0)} · ${limits.tasks_max} tasks · ${limits.cpu_quota_percent}% CPU${limits.verified ? " · verified" : " · unverified"}`;
}

/** Readiness summary: enforced limits, an explicit opt-out, or the blocking reason. */
export function limitsStatusLabel(status: LimitsStatus | null | undefined): string {
  if (!status) return "not reported";
  if (status.requested === "disabled") return "aggregate limits disabled";
  if (status.enforcement_preflight === "passed" && status.configured) {
    const c = status.configured;
    return `cgroup v2 · ${mib(c.memory_max_bytes)} · ${c.tasks_max} tasks · ${c.cpu_quota_percent}% CPU · enforced`;
  }
  return `blocked (${status.reason ?? "enforcement not confirmed"})`;
}

export const OUTCOME: Record<Outcome, { tone: Tone; title: string; detail: string }> = {
  verified: { tone: "ok", title: "Verified repair", detail: "The baseline reproduced the seeded failure, and the patched candidate passed verification." },
  detected: { tone: "warn", title: "Failure detected", detail: "Detection run: the seeded failure reproduced. No patch was requested." },
  no_failure: { tone: "idle", title: "No failure reproduced", detail: "The baseline passed, so there was nothing to repair." },
  repair_unavailable: { tone: "warn", title: "Reproduced; repair unavailable", detail: "The failure reproduced, but no repair provider was available for this job." },
  unexpected_failure: { tone: "bad", title: "Unexpected failure", detail: "The baseline failed with a signature that does not match the seeded defect, so repair was not attempted." },
  invalid_patch: { tone: "bad", title: "Patch rejected", detail: "The proposed patch failed scope, syntax, or safety policy and was not activated." },
  model_error: { tone: "bad", title: "Model error", detail: "The repair provider failed or returned an unusable proposal." },
  unresolved: { tone: "bad", title: "Not repaired", detail: "A candidate was proposed but did not pass verification." },
  infrastructure_error: { tone: "bad", title: "Infrastructure error", detail: "The runner or runtime failed. This result says nothing about the code under test." },
  artifact_error: { tone: "bad", title: "Evidence integrity error", detail: "Recorded artifacts failed verification, so the result is not trusted." },
  timeout: { tone: "bad", title: "Timed out", detail: "The job exceeded its work deadline." },
  cleanup_failed: { tone: "bad", title: "Cleanup failed", detail: "Disposal of job resources could not be confirmed." },
  cancelled: { tone: "warn", title: "Cancelled", detail: "Cancellation was requested and honored." },
  interrupted: { tone: "warn", title: "Interrupted", detail: "The orchestrator stopped while this job was running." },
};
