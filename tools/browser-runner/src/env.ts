/**
 * Environment scrubbing for browser child processes.
 *
 * Playwright forwards the full `process.env` to the Chromium process by
 * default, and Chromium surfaces that environment in its own crash reports
 * and in `/proc/<pid>/environ`. A caller that invokes this runner directly
 * (rather than through the orchestrator's already-scrubbed dispatch) would
 * otherwise leak every host credential into the browser child. This module
 * mirrors the orchestrator's `RUNNER_ENVIRONMENT` allowlist so only OS
 * discovery and browser-cache variables cross the boundary — never an API
 * key, token, or control credential.
 */

/** Variables a browser child process may receive, on any host. */
const BROWSER_ENVIRONMENT_ALLOWLIST: ReadonlySet<string> = new Set([
  "PATH",
  "HOME",
  "XDG_CACHE_HOME",
  "TMPDIR",
  "TMP",
  "TEMP",
  "LANG",
  "LC_ALL",
  "TZ",
  "PLAYWRIGHT_BROWSERS_PATH",
  // Windows process loading and Playwright's native browser cache discovery.
  "SYSTEMROOT",
  "WINDIR",
  "USERPROFILE",
  "LOCALAPPDATA",
]);

/**
 * Returns the environment a browser child may inherit, stripped to the
 * allowlist. The result is a fresh object and never `process.env` itself, so a
 * secret set after module load is still excluded and callers cannot mutate the
 * runner's own environment through the returned mapping.
 */
export function browserEnvironment(
  source: NodeJS.ProcessEnv = process.env,
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const name of BROWSER_ENVIRONMENT_ALLOWLIST) {
    const value = source[name];
    if (value !== undefined) result[name] = value;
  }
  return result;
}
