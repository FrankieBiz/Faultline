/**
 * Runner-side mirror of the canonical execution contracts.
 *
 * `shared/contracts/models.py` is the single schema authority (SpecV1 §5.1).
 * The declarations below match its `ExecutionReport`, `Observation`, and
 * `AssertionResult` field for field; the orchestrator decodes runner output
 * with `ExecutionReport.model_validate_json`, which forbids extra keys. When
 * TypeScript declarations are generated from those models, re-export them
 * here and delete the hand-written copies; the rest of the runner imports
 * contract types only from this module.
 *
 * Job, phase, attempt, snapshot, and artifact registration belong to the
 * orchestrator's execution envelope, not to the runner report.
 */

/** Canonical execution verdict: assertion failures are separate from errors. */
export type ExecutionVerdict = "passed" | "failed" | "error";

/** Category of a failure observation. Several may be reported per execution. */
export type ObservationKind =
  | "assertion"
  | "http_error"
  | "browser_exception"
  | "transport_error"
  | "server_exception"
  | "runner_error";

/** One timestamped observation with structured diagnostic data. */
export interface Observation {
  id: string;
  kind: ObservationKind;
  /** Where the observation came from: `network`, `browser`, `oracle`, or `runner`. */
  source: string;
  /** Bounded, human-readable summary. */
  message: string;
  data: Record<string, unknown>;
  /** UTC RFC 3339 timestamp. */
  timestamp: string;
}

/** Result of one named business assertion. */
export interface AssertionResult {
  id: string;
  passed: boolean;
  /** Bounded summary of what the oracle required. */
  expected: string;
  /** Bounded summary of what actually happened. */
  observed: string;
  duration_ms: number;
}

/** Runner evidence for one scenario execution within one case namespace. */
export interface ExecutionReport {
  execution_id: string;
  /** Namespace sent as `X-Faultline-Case-Id`. */
  case_id: string;
  scenario_id: string;
  verdict: ExecutionVerdict;
  duration_ms: number;
  observations: Observation[];
  assertions: AssertionResult[];
  /** Bounded chronological network, console, and runner log text. */
  raw_logs: string;
}

/**
 * Finer-grained run outcome used for the CLI exit code (SpecV1 §4). The
 * canonical verdict has no timeout value, so a timed-out run reports
 * `error` and keeps the distinction in its exit code and observations.
 */
export type RunOutcome = "passed" | "assertion_failed" | "infrastructure_error" | "timed_out";

/** CLI exit codes required by the runner invocation contract. */
export const EXIT_CODES: Readonly<Record<RunOutcome, number>> = {
  passed: 0,
  assertion_failed: 1,
  infrastructure_error: 2,
  timed_out: 3,
};

/** Maps a run outcome onto the canonical verdict. */
export function verdictFor(outcome: RunOutcome): ExecutionVerdict {
  switch (outcome) {
    case "passed":
      return "passed";
    case "assertion_failed":
      return "failed";
    case "infrastructure_error":
    case "timed_out":
      return "error";
  }
}

/** Role of a saved evidence file. */
export type ArtifactRole = "failure_screenshot" | "final_screenshot" | "trace" | "network_log" | "console_log";

/** One evidence file. Paths are relative to the artifacts directory. */
export interface ArtifactManifestEntry {
  artifact_id: string;
  role: ArtifactRole;
  relative_path: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
}

/**
 * Manifest written as `artifacts.json` next to the evidence, so the
 * orchestrator can verify containment, sizes, and hashes before it
 * registers each file.
 */
export interface ArtifactManifest {
  schema_version: "1.0";
  execution_id: string;
  artifacts: ArtifactManifestEntry[];
}
