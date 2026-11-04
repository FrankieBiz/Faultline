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
 * Hero paste arena: paste a URL and press Enter. The Playwright crawler walks the page within its
 * action budget, skipping destructive controls, and stops at the first failing request; nothing asks
 * for an expected status or error. The quiet ping sends a GET from two fresh sessions instead.
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
        <h1 id={`${ids}-h`}>Make every AI fix <span className="nowrap">prove itself.</span></h1>
        <p className="hero-sub">
          Paste a local or preview URL. A real browser walks it within a fixed action budget, skips destructive controls,
          and stops at the first crash. Then a sandboxed repair has to <strong>pass independent checks before it counts</strong>.
        </p>
        {props.repairCore.tone === "bad" && (
          <p className="hero-offline">
            The engine is offline, so crawls, checks and repairs are paused. Start the local stack
            with <code>./faultline demo</code>, then reload this page.
          </p>
        )}
        <form className="arena" onSubmit={submit} noValidate aria-label="Crawl a URL" data-hunting={hunting || undefined}>
          <label className="sr-only" htmlFor={`${ids}-u`}>Target URL</label>
          <div className="arena-field">
            <input ref={inputRef} id={`${ids}-u`} type="url" inputMode="url" autoComplete="off" spellCheck={false}
              placeholder="http://localhost:3000/..." value={url} onChange={(e) => setUrl(e.target.value)}
              aria-invalid={error ? true : undefined} aria-describedby={error ? `${ids}-e` : `${ids}-k`} />
            <button type="submit" className="btn primary arena-go" disabled={busy}>
              {hunting ? "Crawling…" : "Crawl this URL"}
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
                <button type="button" className="preset" onClick={() => fill("http://localhost:")}>Custom localhost</button>
              </li>
            </ul>
            <p id={`${ids}-k`} className="arena-hint">
              <kbd>Enter</kbd> starts the crawl, or send a{" "}
              <button type="button" className="btn quiet inline-btn" disabled={busy} onClick={() => void run(onPing)}>
                {pinging ? "Pinging…" : "Quick HTTP ping"}
              </button>{" "}from two fresh sessions.
            </p>
          </div>
        </form>
        <div className="hero-paths">
          <p className="hero-core" data-tone={props.repairCore.tone}>
            <span className="hero-core-dot" aria-hidden="true" /><span className="hero-core-k">Repair core</span>{props.repairCore.text}
          </p>
          <a className="hero-demo" href="#demo">
            <span className="hero-demo-k">New here?</span>Guided 3-minute demo<span className="hero-demo-arrow" aria-hidden="true">↓</span>
          </a>
        </div>
      </div>
    </section>
  );
}
