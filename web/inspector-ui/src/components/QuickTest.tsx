"use client";

import { useId, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/faultline-api";

/**
 * Header shortcut for the most common question: does this URL work? A GET is
 * sent from two fresh sessions and judged against HTTP 200; the custom check
 * dialog covers other methods, bodies, and statuses.
 */
export default function QuickTest(props: {
  /** Disabled while another live check or sandbox action holds the dashboard. */
  busy: boolean; testing: boolean;
  onTest: (url: string) => Promise<void>;
  /** Opens the custom check dialog, seeded with whatever is typed so far. */
  onMore: (url: string) => void;
}) {
  const { busy, testing, onTest, onMore } = props;
  const ids = useId();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
      return;
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      setError("The URL must start with http:// or https://.");
      return;
    }
    try {
      await onTest(value);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The URL could not be tested.");
    }
  };

  return (
    <form className="quick-test" onSubmit={submit} noValidate aria-label="Test any URL">
      <label className="quick-label" htmlFor={`${ids}-u`}>Test any URL</label>
      <div className="quick-row">
        <input id={`${ids}-u`} type="url" inputMode="url" autoComplete="off" spellCheck={false}
          placeholder="http://localhost:3000/..." value={url} onChange={(e) => setUrl(e.target.value)}
          aria-invalid={error ? true : undefined} aria-describedby={error ? `${ids}-e` : undefined} />
        <button type="submit" className="btn" disabled={busy}>{testing ? "Testing…" : "Test endpoint"}</button>
        <button type="button" className="btn quiet tool" onClick={() => onMore(url.trim())}>More options</button>
      </div>
      {error && <p id={`${ids}-e`} className="quick-error" role="alert">{error}</p>}
    </form>
  );
}
