"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ApiError, METHODS, type Method } from "@/lib/faultline-api";

export interface ProbeValues {
  title: string; method: Method; url: string; expectedStatus: number;
  /** Parsed JSON body, or undefined when the request sends none. */
  body: unknown; autoRepair: boolean;
}

type Field = "url" | "status" | "body";
const NO_BODY: ReadonlySet<Method> = new Set(["GET", "HEAD"]);
const CHECKOUT_BODY = JSON.stringify({ items: [{ product_id: "trail-mug", quantity: 2 }] }, null, 2);

/** Register an HTTP invariant against any URL, then check it live. */
export default function ProbeDialog(props: {
  open: boolean; storeUrl: string | null;
  onClose: () => void; onSubmit: (values: ProbeValues) => Promise<void>;
}) {
  const { open, storeUrl, onClose, onSubmit } = props;
  const ref = useRef<HTMLDialogElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const ids = useId();
  const [method, setMethod] = useState<Method>("GET");
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("200");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [autoRepair, setAutoRepair] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** The field a client-side check rejected; it is marked invalid and receives focus. */
  const [invalid, setInvalid] = useState<Field | null>(null);
  const statusRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const fields = { url: urlRef, status: statusRef, body: bodyRef };
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      // A draft survives Cancel, but a stale error from the last attempt does not.
      setError(null);
      setInvalid(null);
      dialog.showModal();
      urlRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const reset = () => {
    setMethod("GET"); setUrl(""); setStatus("200"); setTitle(""); setBody(""); setError(null); setInvalid(null);
  };

  const fillCheckout = () => {
    if (!storeUrl) return;
    setMethod("POST");
    setUrl(`${storeUrl.replace(/\/$/, "")}/api/checkout`);
    setStatus("201");
    setTitle("Checkout without a coupon");
    setBody(CHECKOUT_BODY);
    setError(null);
    setInvalid(null);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setInvalid(null);
    const reject = (field: Field, message: string) => {
      setError(message);
      setInvalid(field);
      fields[field].current?.focus();
    };
    let parsedUrl: URL;
    try {
      parsedUrl = new URL(url.trim());
    } catch {
      return reject("url", "Enter a full URL, such as https://api.example.com/health.");
    }
    if (!["http:", "https:"].includes(parsedUrl.protocol)) return reject("url", "The URL must start with http:// or https://.");
    const expectedStatus = Number(status);
    if (!Number.isInteger(expectedStatus) || expectedStatus < 100 || expectedStatus > 599) {
      return reject("status", "Expected status must be a whole number from 100 to 599.");
    }
    let parsedBody: unknown = undefined;
    if (!NO_BODY.has(method) && body.trim()) {
      try {
        parsedBody = JSON.parse(body);
      } catch (e) {
        // The parser's own message names the position, which is what fixes the typo.
        return reject("body", `The request body must be valid JSON${e instanceof SyntaxError ? `: ${e.message}` : ""}.`);
      }
    }
    setSaving(true);
    try {
      await onSubmit({ title: title.trim(), method, url: url.trim(), expectedStatus, body: parsedBody, autoRepair });
      reset();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The probe could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const describe = (field: Field) => invalid === field
    ? { "aria-invalid": true, "aria-describedby": `${ids}-e` } : {};

  return (
    <dialog ref={ref} className="probe-dialog" aria-labelledby={`${ids}-h`} aria-describedby={`${ids}-d`} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <h2 id={`${ids}-h`}>New invariant</h2>
        <p id={`${ids}-d`} className="dialog-lede">
          Probe any URL. FaultLine sends the request from two fresh sessions; it counts as failing only when both miss the expected status the same way.
        </p>
        {storeUrl && (
          <button type="button" className="btn quiet fill" onClick={fillCheckout}>Fill in the live store checkout</button>
        )}
        <div className="field-row">
          <label className="field method-field">
            <span>Method</span>
            <select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
              {METHODS.map((m) => <option key={m}>{m}</option>)}
            </select>
          </label>
          <label className="field grow">
            <span>URL</span>
            <input ref={urlRef} {...describe("url")} type="url" inputMode="url" autoComplete="off" spellCheck={false} required
              placeholder="https://api.example.com/health" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
        </div>
        <div className="field-row">
          <label className="field status-field">
            <span>Expected status</span>
            <input ref={statusRef} {...describe("status")} type="number" inputMode="numeric" min={100} max={599} required value={status} onChange={(e) => setStatus(e.target.value)} />
          </label>
          <label className="field grow">
            <span>Name <span className="muted">optional</span></span>
            <input type="text" maxLength={120} placeholder="Defaults to the method and URL" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
        </div>
        {!NO_BODY.has(method) && (
          <label className="field">
            <span>JSON body <span className="muted">optional, sent as application/json</span></span>
            <textarea ref={bodyRef} {...describe("body")} rows={5} spellCheck={false} value={body} onChange={(e) => setBody(e.target.value)} placeholder='{"items": []}' />
          </label>
        )}
        <label className="check-field">
          <input type="checkbox" checked={autoRepair} onChange={(e) => setAutoRepair(e.target.checked)} />
          <span>If it fails and a registered sandbox repair covers this route and error, start the repair.</span>
        </label>
        <p className="dialog-note">No credentials or custom headers are sent. Redirects are reported, not followed. Responses are read up to 64 KiB.</p>
        {error && <p id={`${ids}-e`} className="notice" data-tone="bad" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn quiet" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="btn primary" disabled={saving}>{saving ? "Saving…" : "Save and check live"}</button>
        </div>
      </form>
    </dialog>
  );
}
