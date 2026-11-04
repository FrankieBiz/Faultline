/**
 * Small inline line glyphs, drawn on a 16 px grid in the current text color. Every one is
 * decorative: the control or line beside it carries the words, so each is hidden from
 * assistive technology. They replace emoji, which render differently on every platform.
 */
const PATHS = {
  check: "M3.5 8.5l3 3 6-7",
  shield: "M8 2l5 2v4c0 3-2.2 5.2-5 6-2.8-.8-5-3-5-6V4z",
  /** A page: where the agent started or navigated. */
  visit: "M4 2.5h5.5L12 5v8.5H4zM9.5 2.5V5H12",
  /** A pointer: a click. */
  click: "M4.5 2.5l7.5 5-3.4.8 1.9 3.6-1.5.8-1.9-3.6-2.6 2.4z",
  /** A text field with a caret: a form fill. */
  fill: "M2.5 4.5h11v7h-11zM5.5 6.5v3",
  /** A cart: adding to a basket or bag. */
  cart: "M1.5 2.5h2l1.5 7h7l1.5-5H4.1M6.5 12.5h.01M11 12.5h.01",
  /** A receipt: an order or checkout submit. */
  order: "M4 2.5h8v11l-2-1.2-2 1.2-2-1.2-2 1.2zM6 5.5h4M6 8h4",
  /** A seismograph spike: the request that broke. */
  rupture: "M1 8.5h3l1.5-5 2.5 9 1.5-4h5.5",
  /** A circle with a rest: held, inconclusive. */
  held: "M8 2.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM5.5 8h5",
  /** A speaker with sound waves: cues on. */
  sound: "M2.5 6h2.5l3.5-3v10L5 10H2.5zM11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.8a6 6 0 0 1 0 8.4",
  /** A speaker with a cross: cues off. */
  muted: "M2.5 6h2.5l3.5-3v10L5 10H2.5zM11 6l3.5 4M14.5 6L11 10",
} as const;

export type GlyphKind = keyof typeof PATHS;

export function Glyph({ kind, className = "glyph-icon" }: { kind: GlyphKind; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false" data-glyph={kind}>
      <path d={PATHS[kind]} />
    </svg>
  );
}

/** A glyph in a hairline seal, for a verdict line such as "Fix verified". */
export function CtaIcon({ kind = "check", className = "btn-icon" }: { kind?: GlyphKind; className?: string }) {
  return (
    <span className={className} aria-hidden="true">
      <svg viewBox="0 0 16 16" focusable="false"><path d={PATHS[kind]} /></svg>
    </span>
  );
}
