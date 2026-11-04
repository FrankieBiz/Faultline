// Real CLI capture and a readable view of its output. No scripted transcript or fake typing.
import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import path from "node:path";

const escapeHtml = (text) => String(text).replace(/[&<>\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);

/** Run the local CLI once, saving stdout and stderr without changing either stream. */
export async function captureGate({ root, out, name, target, maxActions = 100, timeout = 180 }) {
  const args = ["gate", target, "--max-actions", String(maxActions), "--timeout", String(timeout), "--json"];
  const command = `./faultline ${args.join(" ")}`;
  const started = new Date().toISOString();
  const result = await new Promise((resolve, reject) => {
    const child = spawn(path.join(root, "faultline"), args, { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (exitCode, signal) => resolve({ stdout, stderr, exitCode, signal }));
  });
  const stdoutFile = `${name}.stdout.json`;
  const stderrFile = `${name}.stderr.txt`;
  await writeFile(path.join(out, stdoutFile), result.stdout);
  await writeFile(path.join(out, stderrFile), result.stderr);
  let report;
  try { report = JSON.parse(result.stdout); }
  catch { throw new Error(`Gate did not emit JSON (exit ${result.exitCode}); see ${stdoutFile} and ${stderrFile}.`); }
  const capture = {
    command, started_at: started, finished_at: new Date().toISOString(),
    exit_code: result.exitCode, signal: result.signal,
    stdout_file: stdoutFile, stderr_file: stderrFile, report,
  };
  await writeFile(path.join(out, `${name}.capture.json`), JSON.stringify(capture, null, 2) + "\n");
  return capture;
}

/** Selected fields are copied from the parsed stdout; the complete original is kept as a sidecar. */
export async function showGateOutput(page, capture, view = "verdict") {
  const { report } = capture;
  const keys = view === "reproduction"
    ? ["verdict", "reproduction_trail", "agent_remediation_prompt"]
    : ["gate_status", "verdict", "exit_code", "target_url", "summary", "actions_taken", "stop_reason", "failure", "error"];
  const selected = Object.fromEntries(keys.filter((key) => key in report).map((key) => [key, report[key]]));
  if (view === "verdict" && selected.failure) {
    selected.failure = Object.fromEntries(["kind", "method", "endpoint", "status", "message"]
      .filter((key) => key in report.failure).map((key) => [key, report.failure[key]]));
  }
  const title = view === "reproduction" ? "Reproduction and remediation" : "Gate verdict";
  await page.setContent(`<!doctype html><html lang="en"><meta charset="utf-8"><title>Captured CLI output</title>
    <style>
      *{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#0b0b0a;color:#eceef1}
      body{padding:40px 64px;font:22px/1.4 ui-monospace,monospace}
      .label{color:#a9abaf;font:22px/1.4 system-ui,sans-serif;margin:0 0 16px}
      h1{font:600 32px/1.2 system-ui,sans-serif;margin:0 0 16px}
      .command{padding:16px 20px;background:#141412;border:1px solid #565758;border-radius:8px;margin-bottom:20px;overflow-wrap:anywhere}
      pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:20px/1.35 ui-monospace,monospace}
      .footer{margin-top:24px;color:#a9abaf;font:20px/1.4 system-ui,sans-serif}
    </style>
    <p class="label">Captured CLI output · selected fields, unmodified values</p><h1>${escapeHtml(title)}</h1>
    <div class="command">${escapeHtml(capture.command)}</div>
    <pre>${escapeHtml(JSON.stringify(selected, null, 2))}</pre>
    <p class="footer">Actual process exit ${escapeHtml(capture.exit_code)} · complete stdout saved as ${escapeHtml(capture.stdout_file)}</p>
  </html>`);
}
