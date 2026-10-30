"use client";

import { useState } from "react";
import {
  CHAOS_SCENARIOS, CHAOS_SCENARIO_ORDER, type ChaosScenario, type ChaosScenarioId,
} from "@/lib/chaos-scenarios";

const dollars = (cents: number | null) => (cents === null ? "not priced" : `$${(cents / 100).toFixed(2)}`);

function Excerpt({ text, other, kind, label }: { text: string; other: string; kind: "add" | "del"; label: string }) {
  const counterpart = new Set(other.split("\n"));
  return (
    <pre className="code" tabIndex={0} aria-label={label}>
      {text.split("\n").map((line, i) => (
        <span key={i} data-kind={counterpart.has(line) ? "ctx" : kind}>{line || " "}</span>
      ))}
    </pre>
  );
}

/** Authored illustration only: renders chaos-scenarios.ts and never calls the orchestrator. */
export default function AuthoredPreview() {
  const [id, setId] = useState<ChaosScenarioId>("none-type-discount");
  const scenario: ChaosScenario = CHAOS_SCENARIOS[id];
  const { before, after, filePath } = scenario.codeDiffBeforeAfter;
  const expected = scenario.receiptOutput.afterRepair;

  return (
    <details className="preview">
      <summary>Scenario reference · authored preview, not execution evidence</summary>
      <p className="tag">Authored preview · not execution evidence</p>
      <p className="lede">
        Scripted from <code>chaos-scenarios.ts</code>. Nothing here is sent to the orchestrator. Only NoneType
        Discount has a seeded backend scenario; the others are design references.
      </p>

      <div className="seg" role="group" aria-label="Preview scenario">
        {CHAOS_SCENARIO_ORDER.map((key) => (
          <button key={key} type="button" aria-pressed={key === id} onClick={() => setId(key)}>
            {CHAOS_SCENARIOS[key].title}
            <span>{CHAOS_SCENARIOS[key].backend.kind === "seeded" ? "seeded" : "preview only"}</span>
          </button>
        ))}
      </div>

      <p>{scenario.summary}</p>
      <dl className="facts">
        <div>
          <dt>Cart</dt>
          <dd>
            {scenario.customerCart.items.map((item) => `${item.quantity} × ${item.name}`).join(", ")} ·{" "}
            {dollars(scenario.customerCart.subtotalCents)}
          </dd>
        </div>
        <div><dt>Coupon input</dt><dd><code>{JSON.stringify(scenario.customerCart.couponInput)}</code></dd></div>
        <div>
          <dt>Scripted failure</dt>
          <dd>HTTP {scenario.errorToast.httpStatus} · <code>{scenario.errorToast.fingerprint}</code></dd>
        </div>
        <div>
          <dt>Intended result</dt>
          <dd>
            HTTP {expected.httpStatus} ·{" "}
            {expected.kind === "created" ? `order total ${dollars(expected.order.total)}` : expected.message}
          </dd>
        </div>
      </dl>

      <div className="cols">
        <figure>
          <figcaption className="eyebrow">Before · {filePath} (excerpt)</figcaption>
          <Excerpt text={before} other={after} kind="del" label="Authored excerpt before repair" />
        </figure>
        <figure>
          <figcaption className="eyebrow">After · authored, not model output</figcaption>
          <Excerpt text={after} other={before} kind="add" label="Authored excerpt after repair" />
        </figure>
      </div>

      <ol className="script" aria-label="Scripted narrative">
        {scenario.agentTrace.map((step) => (
          <li key={step.atMs}><span className="muted">{step.actor}</span>{step.message}</li>
        ))}
      </ol>
    </details>
  );
}
