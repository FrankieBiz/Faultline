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
export interface Readiness {
  status: "ready" | "detect_only" | "blocked";
  runtime_ready: boolean;
  quarantined: boolean;
  model: Probe | null;
  reason: string | null;
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
  phase: "baseline" | "verification";
  attempt_id: string | null;
  candidate_snapshot_sha256: string;
  artifact_ids: string[];
  report: {
    execution_id: string;
    verdict: "passed" | "failed" | "error" | "timed_out";
    duration_ms: number;
    observations: { id: string; kind: string; message: string }[];
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

/** Server error codes and readiness reasons, phrased for an operator. */
export const REASON: Record<string, string> = {
  isolated_runtime_unavailable:
    "No isolated runtime is configured, so the orchestrator refuses to execute checkout code. Runs stay disabled until containment exists.",
  cleanup_required: "A previous job left resources quarantined. Reset the environment to reconcile them.",
  busy: "Another job holds the runtime lease. Wait for it to finish or cancel it.",
  unauthorized: "The orchestrator rejected the inspector's control token.",
  proxy_unreachable: "The orchestrator is not reachable through the inspector proxy.",
  reset_failed: "Reset could not reconcile owned resources. Check the orchestrator log.",
  not_found: "That job no longer exists in the orchestrator database.",
};

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string) {
    super(REASON[code] ?? `Request failed: ${code.replaceAll("_", " ")} (HTTP ${status}).`);
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
  const code =
    error && typeof error === "object" && "code" in error ? String(error.code)
    : response.status === 502 ? "proxy_unreachable" : `http_${response.status}`;
  throw new ApiError(response.status, code);
}

export function providerName(provider: string, model: string): string {
  if (provider === "deterministic") return `Deterministic fallback · ${model} · no model call`;
  return `${provider === "meta" ? "Meta Model API" : provider} · ${model}`;
}

export function providerLabel(probe: Probe | null): string {
  if (!probe) return "Not probed";
  const name = providerName(probe.provider, probe.model);
  return probe.available ? name : `${name} · unavailable (${probe.reason ?? "no reason given"})`;
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
