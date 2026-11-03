"use client";

import { useEffect, useId, useRef, useState } from "react";
import { REASON, mib, type Readiness, type Tone } from "@/lib/faultline-api";

type PillTone = Tone | "active";
interface Fact { key: string; value: string; tone: Tone }
export interface HostRuntime { tone: PillTone; label: string; facts: Fact[]; note: string | null }

/**
 * Where candidate code runs, as readiness reports it. Green only when the isolated runtime is up
 * and the kernel read back the cgroup v2 limits; nothing here is assumed from the platform.
 */
export function hostRuntime(readiness: Readiness | null, error: string | null): HostRuntime {
  if (!readiness) {
    return { tone: error ? "bad" : "active", label: error ? "Unreachable" : "Checking…", facts: [], note: error };
  }
  const { host, resource_limits: limits, runtime_ready: ready } = readiness;
  const os = host?.os || null;
  const bubblewrap = host?.runtime_kind === "isolated-browser";
  const configured = limits?.requested === "required" && limits.enforcement_preflight === "passed"
    && limits.mode === "cgroup-v2-scope" ? limits.configured : null;
  const disabled = limits?.requested === "disabled";

  const facts: Fact[] = [
    { key: "Host kernel", value: os ? `${os}${host?.kernel ? ` ${host.kernel}` : ""}` : "Not reported by this engine", tone: "idle" },
    { key: "Kernel sandbox", tone: ready ? "ok" : "bad",
      value: !ready ? "Unavailable" : bubblewrap ? "Bubblewrap · own Linux namespaces per run" : "Isolated runtime ready" },
    { key: "Read-only root", tone: ready && bubblewrap ? "ok" : ready ? "idle" : "bad",
      value: !ready ? "No sandbox to mount" : bubblewrap ? "Host paths bound read-only · writes to private tmpfs" : "Not reported by this runtime" },
  ];
  if (configured) {
    facts.push(
      { key: "Memory", value: `${mib(configured.memory_max_bytes)} hard cap`, tone: "ok" },
      { key: "Tasks", value: `${configured.tasks_max} processes max`, tone: "ok" },
      { key: "CPU", value: `${configured.cpu_quota_percent}% quota`, tone: "ok" },
      { key: "Enforcement", value: "Kernel read-back passed", tone: "ok" },
    );
  } else {
    facts.push({
      key: "Bounds", tone: disabled ? "warn" : limits ? "bad" : "idle",
      value: disabled ? "cgroup limits disabled by the operator"
        : limits ? `Not enforced (${limits.reason ?? limits.enforcement_preflight ?? "not confirmed"})` : "Not reported by this engine",
    });
  }

  const tone: PillTone = !ready ? "bad" : configured ? "ok" : limits && !disabled ? "bad" : "warn";
  const label = !ready ? "Sandbox unavailable"
    : configured ? `${os ?? "Kernel"} · cgroup v2`
    : limits && !disabled ? "Limits not enforced" : "Platform isolated";
  const note = !ready ? REASON[readiness.reason ?? ""] ?? "No isolated runtime is ready, so no candidate code runs."
    : configured ? "Namespaces plus cgroup limits on a shared kernel, not a VM. Limits are read back from the kernel at every launch."
    : "Candidates run in the isolated runtime, but aggregate memory, task, and CPU bounds are not confirmed.";
  return { tone, label, facts, note };
}

/**
 * Header capability pill: the host runtime in two words, with the sandbox, read-only root, and
 * resource bounds behind it. A disclosure, not a dialog: Escape, a click outside, or moving focus
 * away closes it, and focus returns to the pill.
 */
export default function RuntimePill({ readiness, error }: { readiness: Readiness | null; error: string | null }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const titleId = useId();
  const runtime = hostRuntime(readiness, error);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  return (
    <div ref={root} className="runtime"
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        event.stopPropagation();
        setOpen(false);
        trigger.current?.focus();
      }}
      onBlur={(event) => { if (open && !event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
      <button ref={trigger} type="button" className="runtime-pill" data-tone={runtime.tone}
        aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)}>
        <span className="readiness-dot" aria-hidden="true" />
        <span className="runtime-key">Runtime:</span> <span className="runtime-value">{runtime.label}</span>
        <span className="runtime-chev" aria-hidden="true" />
      </button>
      {open && (
        <div id={panelId} className="runtime-panel" role="group" aria-labelledby={titleId}>
          <p id={titleId} className="runtime-title">Host runtime <span className="muted">· from engine readiness</span></p>
          {runtime.facts.length > 0 && (
            <dl className="runtime-facts">
              {runtime.facts.map((fact) => (
                <div key={fact.key}><dt>{fact.key}</dt><dd data-tone={fact.tone}>{fact.value}</dd></div>
              ))}
            </dl>
          )}
          {runtime.note && <p className="runtime-note">{runtime.note}</p>}
        </div>
      )}
    </div>
  );
}
