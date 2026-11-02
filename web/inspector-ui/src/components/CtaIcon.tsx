/** Trailing icon for a call to action, in its own circular well. Decorative: the button's text is its name. */
const PATHS = {
  arrow: "M3 8h10M9 4l4 4-4 4",
  check: "M3.5 8.5l3 3 6-7",
  shield: "M8 2l5 2v4c0 3-2.2 5.2-5 6-2.8-.8-5-3-5-6V4z",
} as const;

export type CtaIconKind = keyof typeof PATHS;

export function CtaIcon({ kind = "arrow", className = "btn-icon" }: { kind?: CtaIconKind; className?: string }) {
  return (
    <span className={className} aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false"><path d={PATHS[kind]} /></svg>
    </span>
  );
}
