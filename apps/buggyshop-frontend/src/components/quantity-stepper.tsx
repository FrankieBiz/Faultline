"use client";

import { useId } from "react";
import { MAX_QUANTITY, MIN_QUANTITY, clampQuantity } from "@/lib/cart";

/**
 * Parses free-form quantity text. Returns `null` unless the text is a whole
 * number inside the accepted range, matching the backend's strict rules.
 */
export function parseQuantityText(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d{1,2}$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value >= MIN_QUANTITY && value <= MAX_QUANTITY ? value : null;
}

interface QuantityStepperProps {
  /** Raw text in the field; the parent derives the numeric value. */
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}

/**
 * Quantity field labelled "Quantity" with decrease/increase buttons. The
 * input stays editable as text so a shopper (or a test) can type a value; an
 * out-of-range entry is flagged inline instead of being silently corrected.
 */
export function QuantityStepper({ value, onChange, disabled = false }: QuantityStepperProps) {
  const inputId = useId();
  const hintId = useId();
  const parsed = parseQuantityText(value);
  const invalid = parsed === null;
  // Step from the nearest valid value, so "+" or "−" after typing 12 lands on 10 or 9.
  const base = parsed ?? clampQuantity(Number.parseInt(value, 10) || MIN_QUANTITY);

  return (
    <div>
      <label htmlFor={inputId} className="block font-bold">
        Quantity
      </label>
      <div className="mt-2 flex h-12 w-fit items-stretch overflow-hidden rounded-md border-[1.5px] border-stone focus-within:border-blaze">
        <button
          type="button"
          aria-label="Decrease quantity"
          disabled={disabled || base <= MIN_QUANTITY}
          onClick={() => onChange(String(clampQuantity(base - 1)))}
          className="w-12 text-xl font-bold transition-colors hover:bg-mist disabled:cursor-not-allowed disabled:opacity-35"
        >
          −
        </button>
        <input
          id={inputId}
          type="number"
          inputMode="numeric"
          min={MIN_QUANTITY}
          max={MAX_QUANTITY}
          step={1}
          value={value}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={hintId}
          onChange={(event) => onChange(event.target.value)}
          className="w-16 border-x-[1.5px] border-stone bg-white text-center text-lg font-bold tabular-nums outline-none disabled:bg-mist"
        />
        <button
          type="button"
          aria-label="Increase quantity"
          disabled={disabled || base >= MAX_QUANTITY}
          onClick={() => onChange(String(clampQuantity(base + 1)))}
          className="w-12 text-xl font-bold transition-colors hover:bg-mist disabled:cursor-not-allowed disabled:opacity-35"
        >
          +
        </button>
      </div>
      <p id={hintId} className={`mt-2 text-sm ${invalid ? "font-semibold text-alarm" : "text-moss"}`}>
        {invalid
          ? `Enter a whole number from ${MIN_QUANTITY} to ${MAX_QUANTITY}.`
          : `Up to ${MAX_QUANTITY} per item.`}
      </p>
    </div>
  );
}
