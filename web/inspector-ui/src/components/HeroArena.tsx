"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/faultline-api";

const parse = (url: string | null) => {
  try {
    return url ? new URL(url) : null;
  } catch {
    return null;
  }
};

/**
 * Hero paste arena: paste a URL, press Enter, and the autonomous agent does the rest. The
 * Playwright crawler clicks, fills, and submits everything on the page until a request fails;
 * nothing asks for an expected status or error. The quiet ping sends a GET from two fresh sessions.
 */
export default function HeroArena(props: {
  storefrontUrl: string;
  /** The demo store's API origin, when the engine reports one. */
  apiUrl: string | null;
  /** Disabled while another live check, crawl, or sandbox action holds the dashboard. */
  busy: boolean; hunting: boolean; pinging: boolean;
  onHunt: (url: string) => Promise<void>;
  onPing: (url: string) => Promise<void>;
  /** The engine that writes repairs, as readiness reports it. */
  repairCore: { tone: "ok" | "warn" | "bad" | "idle"; text: string };
}) {
  const { storefrontUrl, busy, hunting, pinging, onHunt, onPing } = props;
  const ids = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const apiUrl = parse(props.apiUrl)?.origin ?? "http://127.0.0.1:8000";
  const presets = [
    { label: `Storefront (port ${parse(storefrontUrl)?.port || "3000"})`, value: storefrontUrl },
    { label: `Backend API (port ${parse(apiUrl)?.port || "8000"})`, value: apiUrl },
    // A standalone app outside the demo stack, so a hunt can run against code FaultLine has never seen.
    { label: "AuraScale Cloud (port 5050)", value: "http://127.0.0.1:5050" },
  ];

  /** Normalizes the typed URL, or shows why it cannot be used and returns null. */
  const target = (): string | null => {
    setError(null);
    // "localhost:3000/health" means http; only an explicit scheme overrides that.
    const typed = url.trim();
    const value = /^[a-z][a-z\d+.-]*:\/\//i.test(typed) ? typed : `http://${typed}`;
    if (value !== typed) setUrl(value);
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch {
      setError("Enter a full URL, such as http://localhost:3000/.");
      return null;
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      setError("The URL must start with http:// or https://.");
      return null;
    }
    return value;
  };

  const run = async (action: (url: string) => Promise<void>) => {
    const value = target();
    if (!value) return;
    try {
      await action(value);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The URL could not be tested.");
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run(onHunt);
  };

  const fill = (value: string) => {
    setUrl(value);
    setError(null);
    // Leave the caret at the end so a custom port or path can be typed straight away.
    requestAnimationFrame(() => {
      const input = inputRef.current;
      input?.focus();
      input?.setSelectionRange(value.length, value.length);
    });
  };

  return (
    <section className="hero" aria-labelledby={`${ids}-h`}>
      <div className="shell hero-inner">
        <p className="hero-kicker"><span className="hero-live" aria-hidden="true" />The autonomous immune system for AI coding agents and web apps</p>
        <h1 id={`${ids}-h`}>FaultLine Autonomous Bug Hunter</h1>
        <p className="hero-sub">
          Paste any local or web URL. The agent clicks every button, fills every form, and <strong>catches silent regressions before code goes live</strong>.
          Then a sandboxed repair has to pass independent checks before it counts.
        </p>
        <p className="hero-core" data-tone={props.repairCore.tone}>
          <span className="hero-core-dot" aria-hidden="true" /><span className="hero-core-k">Repair core</span>{props.repairCore.text}
        </p>
        <form className="arena" onSubmit={submit} noValidate aria-label="Autonomous bug hunt" data-hunting={hunting || undefined}>
          <label className="sr-only" htmlFor={`${ids}-u`}>Target URL</label>
          <div className="arena-field">
            <span className="arena-prompt" aria-hidden="true">›</span>
            <input ref={inputRef} id={`${ids}-u`} type="url" inputMode="url" autoComplete="off" spellCheck={false}
              placeholder="http://localhost:3000/..." value={url} onChange={(e) => setUrl(e.target.value)}
              aria-invalid={error ? true : undefined} aria-describedby={error ? `${ids}-e` : `${ids}-k`} />
            <button type="submit" className="btn primary arena-go" disabled={busy}>
              <span aria-hidden="true">🚀 </span>{hunting ? "Agent hunting…" : "Unleash Autonomous Agent"}
            </button>
          </div>
          {error && <p id={`${ids}-e`} className="arena-error" role="alert">{error}</p>}
          <div className="arena-below">
            <ul className="presets" aria-label="Quick targets">
              {presets.map((preset) => (
                <li key={preset.label}>
                  <button type="button" className="preset" aria-pressed={url === preset.value} onClick={() => fill(preset.value)}>
                    {preset.label}
                  </button>
                </li>
              ))}
              <li>
                <button type="button" className="preset" onClick={() => fill("http://localhost:")}>Custom Localhost</button>
              </li>
            </ul>
            <p id={`${ids}-k`} className="arena-hint">
              <kbd>Enter</kbd> to unleash ·{" "}
              <button type="button" className="btn quiet inline-btn" disabled={busy} onClick={() => void run(onPing)}>
                {pinging ? "Pinging…" : "Quick HTTP Ping"}
              </button>
            </p>
          </div>
        </form>
      </div>
    </section>
  );
}
