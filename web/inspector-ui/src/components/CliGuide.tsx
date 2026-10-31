"use client";

import { useEffect, useId, useRef, useState } from "react";

/** Every command here exists in services/repair-orchestrator/app/cli.py; keep them in step. */
const STEPS: { title: string; commands: string[]; terminal: string; dashboard: string }[] = [
  {
    title: "Initialize",
    commands: ["faultline init"],
    terminal: "Detects the stack and writes faultline.toml: project commands, the repair scope, sandbox limits, and a service_health rule.",
    dashboard: "Its [scenarios] and [[invariants.rule]] entries appear in the rail under faultline.toml.",
  },
  {
    title: "Check readiness",
    commands: ["faultline doctor"],
    terminal: "Checks Bubblewrap, cgroup v2, uv, Node.js, and META_API_KEY, and whether the orchestrator (port 9000) and store (port 8000) answer.",
    dashboard: "The sandbox status in the header. Containment and environment reset sit in the setup panel under past runs.",
  },
  {
    title: "Gate live invariants",
    commands: ["faultline check --port 8000", "faultline check --port 8000 --json"],
    terminal: "Sends every HTTP rule and scenario in faultline.toml from two fresh sessions; each assertion must pass in both. Exit 0 when all pass and the sandbox prerequisites are present, 1 otherwise. --json prints one object for CI, and --repair proposes a sandbox candidate for a reproduced failure without applying it.",
    dashboard: "Run live check sends the same rule through the same engine and shows both sessions' evidence. The rail keeps each rule's last verdict.",
  },
  {
    title: "Probe the demo store",
    commands: ["faultline verify"],
    terminal: "Sends one checkout request to the store on port 8000 and reports whether the seeded defect is active.",
    dashboard: "Check checkout live in the live store bar.",
  },
  {
    title: "Reproduce and repair",
    commands: ["faultline run checkout_api --detect", "faultline run checkout_api"],
    terminal: "Requires two matching isolated failures before any model call, then verifies the candidate and writes a checksummed proof. Exit 0 verified, 10 detected, 11 not reproduced, 20 not repaired.",
    dashboard: "Run sandbox repair, or Run detection only when no repair provider is available. Terminal runs are not listed in this page's history.",
  },
  {
    title: "Watch a run",
    commands: ["faultline listen", "faultline listen --plain"],
    terminal: "Streams the newest orchestrator job as a live HUD: seven stages, assertion marks, and the outcome's exit code. --plain prints one line per stage for CI logs.",
    dashboard: "Start a run here, then listen to it in the terminal. Both read the same job events.",
  },
  {
    title: "Open the dashboard",
    commands: ["faultline dashboard"],
    terminal: "Opens this Inspector on port 4000, starting the built app when nothing serves the port.",
    dashboard: "You are here.",
  },
  {
    title: "Deliver",
    commands: ["faultline diff", "faultline apply", "faultline revert"],
    terminal: "Prints the newest run's candidate diff with its outcome, writes the newest verified fix to the store's working source, or restores the seeded defect. Nothing is pushed or deployed.",
    dashboard: "Apply fix and Revert store in the live store bar.",
  },
];


/** Command-line flags in prose, set as code so "--repair" never breaks across a line. */
function withFlags(text: string) {
  return text.split(/(--[a-z]+)/).map((part, i) => (i % 2 ? <code key={i} className="flag">{part}</code> : part));
}

function CopyCommand({ command, onCopied }: { command: string; onCopied: (text: string) => void }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      onCopied(`Copied ${command}`);
    } catch {
      onCopied("The clipboard is unavailable here. Select the command to copy it.");
    }
  };
  return (
    <li className="cmd">
      <code><span className="cmd-prompt" aria-hidden="true">$ </span>{command}</code>
      <button type="button" className="btn quiet cmd-copy" onClick={copy} aria-label={`Copy ${command}`}>Copy</button>
    </li>
  );
}

/**
 * The terminal and the dashboard, side by side, for each step of the developer workflow.
 * The dialog element owns its open state: each new `request` opens it, and Escape or Close
 * shut it natively, so a reopen can never race the asynchronous close event.
 */
export default function CliGuide({ request }: { request: number }) {
  const ref = useRef<HTMLDialogElement>(null);
  const ids = useId();
  const [copied, setCopied] = useState("");

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || request === 0 || dialog.open) return;
    setCopied("");
    dialog.showModal();
  }, [request]);

  const close = () => ref.current?.close();

  return (
    <dialog ref={ref} className="probe-dialog guide-dialog" aria-labelledby={`${ids}-h`} aria-describedby={`${ids}-d`}>
      <div className="guide">
        <div className="guide-head">
          <div>
            <p className="eyebrow">Quick sheet</p>
            <h2 id={`${ids}-h`}>Developer workflow</h2>
          </div>
          <button type="button" className="btn quiet" onClick={close}>Close</button>
        </div>
        <p id={`${ids}-d`} className="dialog-lede">
          Two surfaces over one engine, both reading <code>faultline.toml</code>. <code>faultline run</code> executes in the terminal and keeps its proof in <code>.faultline/runs</code>. Runs started here go through the orchestrator, and <code>listen</code>, <code>diff</code>, and <code>apply</code> read those same jobs from the terminal.
        </p>
        <ol className="guide-steps">
          <li className="guide-legend" aria-hidden="true">
            <span />
            <span>Terminal</span>
            <span>Dashboard</span>
          </li>
          {STEPS.map((step, i) => (
            <li key={step.title} className="guide-step">
              <span className="guide-index" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
              <div className="guide-terminal">
                <h3>{step.title}</h3>
                <ul className="cmds" aria-label={`${step.title} commands`}>
                  {step.commands.map((command) => <CopyCommand key={command} command={command} onCopied={setCopied} />)}
                </ul>
                <p>{withFlags(step.terminal)}</p>
              </div>
              <p className="guide-dashboard"><span className="sr-only">In the dashboard: </span>{step.dashboard}</p>
            </li>
          ))}
        </ol>
        <p className="dialog-note">
          From a clone, run each command through the launcher at the repository root, as in <code>./faultline check --port 8000</code>. It also works from another project by absolute path or a symlink on <code>PATH</code>.
          Press <kbd>?</kbd> anywhere outside a text field to open this sheet.
        </p>
        <p className="sr-only" role="status" aria-live="polite">{copied}</p>
        {copied && <p className="guide-copied" aria-hidden="true">{copied}</p>}
      </div>
    </dialog>
  );
}
