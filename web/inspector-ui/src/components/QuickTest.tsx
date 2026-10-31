"use client";

import { useId, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/faultline-api";

/**
 * Header test bar: paste a URL and FaultLine works out what "broken" means by itself. The
 * primary action lets a Playwright crawler click and submit everything on the page until a
 * request fails; the ping sends a GET from two fresh sessions. Neither asks for an expected
 * status or error.
 */
export default function QuickTest(props: {
  /** Disabled while another live check, crawl, or sandbox action holds the dashboard. */
  busy: boolean; breaking: boolean; pinging: boolean;
  onBreak: (url: string) => Promise<void>;
  onPing: (url: string) => Promise<void>;
}) {
  const { busy, breaking, pinging, onBreak, onPing } = props;
  const ids = useId();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

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
    void run(onBreak);
  };

  return (
    <form className="quick-test" onSubmit={submit} noValidate aria-label="Break any page">
      <label className="quick-label" htmlFor={`${ids}-u`}>Target URL</label>
      <div className="quick-row">
        <input id={`${ids}-u`} type="url" inputMode="url" autoComplete="off" spellCheck={false}
          placeholder="http://localhost:3000/..." value={url} onChange={(e) => setUrl(e.target.value)}
          aria-invalid={error ? true : undefined} aria-describedby={error ? `${ids}-e` : undefined} />
        <button type="submit" className="btn primary quick-break" disabled={busy}>
          <span aria-hidden="true" className="quick-bolt">⚡</span>{breaking ? "Crawling…" : "Auto-Break Page (Playwright)"}
        </button>
        <button type="button" className="btn quick-ping" disabled={busy} onClick={() => void run(onPing)}>
          {pinging ? "Pinging…" : "Quick HTTP Ping"}
        </button>
      </div>
      {error && <p id={`${ids}-e`} className="quick-error" role="alert">{error}</p>}
    </form>
  );
}
