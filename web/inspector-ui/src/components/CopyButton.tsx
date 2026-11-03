"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A polite status line for copy and download feedback. The region is cleared before each message
 * and refilled a beat later, so pressing Copy twice is heard twice instead of once.
 */
export function useAnnouncer() {
  const [message, setMessage] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const announce = useCallback((text: string) => {
    clearTimeout(timer.current);
    setMessage("");
    timer.current = setTimeout(() => setMessage(text), 100);
  }, []);
  return [message, announce] as const;
}

/**
 * Copies `text` and reports the outcome through `onCopied`, for a live region the caller renders.
 * Focus stays on the button; its label reads "Copied" for a moment as the sighted cue.
 */
export function CopyButton({ text, label, onCopied, className = "btn quiet gate-copy" }: {
  text: string; label: string; onCopied: (message: string) => void; className?: string;
}) {
  const [done, setDone] = useState(false);
  const restore = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(restore.current), []);
  const copy = async () => {
    clearTimeout(restore.current);
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      onCopied(`Copied ${label}`);
      restore.current = setTimeout(() => setDone(false), 1600);
    } catch {
      setDone(false);
      onCopied("The clipboard is unavailable here. Select the text to copy it.");
    }
  };
  return (
    <button type="button" className={className} data-done={done || undefined} onClick={copy} aria-label={`Copy ${label}`}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}
