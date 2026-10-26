import { useId } from "react";

interface SummaryRowProps {
  label: string;
  value: string;
  emphasis?: boolean;
}

/**
 * One label/value pair in a totals list. The value is explicitly labelled by
 * its term so it can be located by role and label ("Subtotal", "Total").
 */
export function SummaryRow({ label, value, emphasis = false }: SummaryRowProps) {
  const labelId = useId();
  return (
    <div
      className={`flex items-baseline justify-between gap-4 ${
        emphasis ? "mt-2 border-t-2 border-spruce pt-3 text-xl font-extrabold" : "py-1"
      }`}
    >
      <dt id={labelId}>{label}</dt>
      <dd aria-labelledby={labelId} className="tabular-nums">
        {value}
      </dd>
    </div>
  );
}
