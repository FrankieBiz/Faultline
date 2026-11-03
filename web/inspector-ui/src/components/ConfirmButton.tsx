"use client";

import { useId, useRef, useState, type ReactNode } from "react";

/**
 * A destructive action that asks once, inline: the first press arms it and the second confirms.
 * Cancel, Escape, or moving focus away disarms it. There is no timeout, so nobody is rushed.
 */
export default function ConfirmButton(props: {
  className: string; disabled: boolean;
  /** The armed button's label, e.g. "Confirm revert?". */
  confirmLabel: string;
  /** What the action does, read with both the trigger and the armed button. */
  description?: string;
  /** The action is in flight; its label says so and assistive tech hears it as busy. */
  busy?: boolean;
  onConfirm: () => void;
  children: ReactNode;
}) {
  const { className, disabled, confirmLabel, description, busy, onConfirm, children } = props;
  const [armed, setArmed] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const descriptionId = useId();
  const describedBy = description ? descriptionId : undefined;
  const hint = description ? <span id={descriptionId} className="sr-only">{description}</span> : null;
  const disarm = (refocus: boolean) => {
    setArmed(false);
    if (refocus) requestAnimationFrame(() => trigger.current?.focus());
  };

  // An action that becomes unavailable while armed asks again from the start once it returns.
  if (armed && disabled) setArmed(false);
  if (!armed || disabled) {
    return <>
      <button ref={trigger} type="button" className={className} disabled={disabled} aria-describedby={describedBy}
        aria-busy={busy || undefined} onClick={() => setArmed(true)}>{children}</button>{hint}
    </>;
  }
  return (
    <span className="confirm" role="group" aria-label={confirmLabel}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); disarm(true); } }}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) disarm(false); }}>
      {/* Keep focus inside on press, so a click in browsers that do not focus buttons cannot disarm first. */}
      <button type="button" className={className} data-confirm autoFocus aria-describedby={describedBy} onMouseDown={(e) => e.preventDefault()}
        onClick={() => { disarm(true); onConfirm(); }}>
        <span aria-hidden="true">⚠ </span>{confirmLabel}
      </button>
      <button type="button" className={className} onMouseDown={(e) => e.preventDefault()} onClick={() => disarm(true)}>Cancel</button>
      {hint}
    </span>
  );
}
