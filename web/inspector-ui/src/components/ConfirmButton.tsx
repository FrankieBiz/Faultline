"use client";

import { useRef, useState, type ReactNode } from "react";

/**
 * A destructive action that asks once, inline: the first press arms it and the second confirms.
 * Cancel, Escape, or moving focus away disarms it. There is no timeout, so nobody is rushed.
 */
export default function ConfirmButton(props: {
  className: string; disabled: boolean;
  /** The armed button's label, e.g. "Confirm revert?". */
  confirmLabel: string;
  onConfirm: () => void;
  children: ReactNode;
}) {
  const { className, disabled, confirmLabel, onConfirm, children } = props;
  const [armed, setArmed] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const disarm = (refocus: boolean) => {
    setArmed(false);
    if (refocus) requestAnimationFrame(() => trigger.current?.focus());
  };

  // An action that becomes unavailable while armed asks again from the start once it returns.
  if (armed && disabled) setArmed(false);
  if (!armed || disabled) {
    return <button ref={trigger} type="button" className={className} disabled={disabled} onClick={() => setArmed(true)}>{children}</button>;
  }
  return (
    <span className="confirm" role="group" aria-label={confirmLabel}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); disarm(true); } }}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) disarm(false); }}>
      {/* Keep focus inside on press, so a click in browsers that do not focus buttons cannot disarm first. */}
      <button type="button" className={className} data-confirm autoFocus onMouseDown={(e) => e.preventDefault()}
        onClick={() => { disarm(true); onConfirm(); }}>
        <span aria-hidden="true">⚠ </span>{confirmLabel}
      </button>
      <button type="button" className={className} onMouseDown={(e) => e.preventDefault()} onClick={() => disarm(true)}>Cancel</button>
    </span>
  );
}
