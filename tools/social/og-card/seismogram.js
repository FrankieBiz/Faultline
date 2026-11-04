// The seismogram of the recorded repair, built from the record itself.
//
// Every time on the x axis comes from docs/replay/<job>/job.json (stage events and the verification
// execution), read at render time. The amplitude is not a measurement: the cards say so.
export const JOB_ID = "3573b32b-09bd-4f14-897d-cf6dccf9b118";
export const JOB_URL = `/docs/replay/${JOB_ID}/job.json`;
export const EVAL_URL = "/docs/evidence/2026-10-28-evaluation-deterministic.json";
// The second evaluation run of the same authored corpus; the card only prints what both runs agree on.
export const EVAL_URL_2 = "/docs/evidence/2026-10-28-evaluation-deepseek-v4-pro.json";

const ms = (iso) => Date.parse(iso);

/** Reads the recorded job and returns the facts the cards print, each derived from the record. */
export async function loadRun() {
  const job = await (await fetch(JOB_URL)).json();
  const t0 = ms(job.job.created_at);
  const at = (stage) => {
    const event = job.events.find((e) => e.stage === stage);
    if (!event) throw new Error(`job.json has no ${stage} event`);
    return (ms(event.timestamp) - t0) / 1000;
  };
  const verificationRun = job.executions.find((e) => e.phase === "verification");
  const baselineRun = job.executions.find((e) => e.phase === "baseline");
  const verification = verificationRun.report;
  const baseline = baselineRun.report;
  const since = (iso) => (ms(iso) - t0) / 1000;
  const attempt = job.attempts[0];
  const checks = verification.assertions;
  const passed = checks.filter((a) => a.passed).length;
  const http500 = baseline.observations.find((o) => o.kind === "http_error" && o.data && o.data.status === 500);
  const run = {
    jobId: job.job.id,
    outcome: job.job.outcome,
    provider: attempt.validation_result.provider,
    model: attempt.validation_result.model,
    generationMs: attempt.validation_result.generation_ms,
    tokens: attempt.prompt_tokens + attempt.completion_tokens,
    checks: checks.length,
    passed,
    byKind: checks.reduce((acc, a) => { const k = a.id.split(".")[0]; acc[k] = (acc[k] || 0) + 1; return acc; }, {}),
    status500: Boolean(http500),
    t: {
      baseline: at("baseline"),
      // The rupture is the moment the baseline browser saw the HTTP 500, not the stage change after it.
      rupture: http500 ? since(http500.timestamp) : NaN,
      diagnosing: at("diagnosing"),
      patch: at("patch_validation"),
      activating: at("activating"),
      verification: at("verification"),
      cleanup: at("cleanup"),
      end: at("completed"),
      checksFrom: since(verificationRun.started_at),
      checksTo: since(verificationRun.finished_at),
    },
  };
  if (run.outcome !== "verified" || run.passed !== run.checks || !run.status500 || !(run.t.rupture < run.t.diagnosing)) {
    throw new Error("job.json no longer records a verified run with a baseline HTTP 500");
  }
  return run;
}

/** Reads the authored wrong-fix evaluation and returns the counts the 201-trap card prints. */
export async function loadEvaluation() {
  const [record, second] = await Promise.all([EVAL_URL, EVAL_URL_2].map(async (u) => (await fetch(u)).json()));
  const s = record.patches.summary;
  const trap = record.patches.cases.find((c) => c.id === "early_return_unsaved");
  const trap2 = second.patches.cases.find((c) => c.id === "early_return_unsaved");
  if (JSON.stringify(s) !== JSON.stringify(second.patches.summary) || JSON.stringify(trap) !== JSON.stringify(trap2) || record.oracle !== second.oracle) {
    throw new Error("the two evaluation runs no longer agree on the authored patch results");
  }
  if (!trap || trap.kind !== "wrong" || !trap.symptom_check_accepts || trap.faultline_accepts || trap.symptom_status !== 201) {
    throw new Error("early_return_unsaved no longer matches the 201-trap story");
  }
  const oracle = /\((\d+) independent HTTP business checks\)/.exec(record.oracle);
  if (!oracle) throw new Error("the evaluation record no longer names its HTTP business check count");
  return {
    businessChecks: Number(oracle[1]),
    wrong: s.wrong,
    naiveAccepted: s.wrong_accepted_by_symptom_check,
    faultlineAccepted: s.wrong_accepted_by_faultline,
    correct: s.correct,
    correctAccepted: s.correct_accepted_by_faultline,
    trapFailing: trap.failing.map((id) => id.replace(/^regression\./, "")),
  };
}

// Deterministic texture: a sum of incommensurate sines, so every render draws the same line.
const tex = (t, a, b, c) => Math.sin(t * a + 0.7) * 0.55 + Math.sin(t * b + 2.1) * 0.3 + Math.sin(t * c + 4.4) * 0.15;

/**
 * Builds the trace as colored SVG segments over [0, run.t.end].
 * opts: width and height of the trace box in px, stroke width (the rupture draws 1.3x heavier).
 */
export function traceSVG(run, opts) {
  const { width: W, height: H, stroke = 2, padTop = 0 } = opts;
  const weight = { "seg-rupture": stroke * 1.3 };
  const T = run.t.end;
  const mid = padTop + (H - padTop) * 0.5;
  const half = (H - padTop) * 0.5;
  const R = run.t.rupture;
  const ringEnd = R + 0.95;
  const step = T / (W * 2);
  const x = (t) => (t / T) * W;

  function y(t) {
    let v;
    if (t < run.t.baseline) v = tex(t, 41, 97, 173) * 0.012;
    else if (t < R) v = tex(t, 57, 131, 211) * 0.04 + (Math.abs(t - (run.t.baseline + 0.35)) < 0.05 ? Math.sin(t * 160) * 0.08 : 0);
    else if (t < ringEnd) {
      const d = t - R;
      const env = (1 - Math.exp(-d / 0.01)) * Math.exp(-d / 0.24);
      const carrier = Math.sin(2 * Math.PI * (19 * d - 3.5 * d * d)) * (0.72 + 0.28 * Math.sin(2 * Math.PI * 2.7 * d + 1.1));
      v = env * carrier * 0.98 + tex(t, 57, 131, 211) * 0.03;
    } else if (t < run.t.patch) v = tex(t, 3.1, 7.3, 61) * 0.035;
    else if (t < run.t.verification) {
      const d = t - run.t.patch;
      v = Math.exp(-d / 0.05) * Math.sin(d * 120) * 0.16 + tex(t, 47, 113, 199) * 0.03;
    } else if (t < run.t.cleanup) v = tex(t, 23, 89, 157) * 0.02;
    else v = tex(t, 23, 89, 157) * 0.02 * Math.exp(-(t - run.t.cleanup) / 0.06);
    return mid - v * half;
  }

  const segments = [
    { cls: "seg-pre", from: 0, to: R },
    { cls: "seg-rupture", from: R, to: R + 0.62 },
    { cls: "seg-model", from: R + 0.62, to: run.t.checksTo },
    // The line settles green only once the verification run has recorded its result.
    { cls: "seg-verified", from: run.t.checksTo, to: T },
  ];
  const paths = segments.map(({ cls, from, to }) => {
    const pts = [];
    for (let t = from; t < to; t += step) pts.push(`${x(t).toFixed(2)},${y(t).toFixed(2)}`);
    pts.push(`${x(to).toFixed(2)},${y(to).toFixed(2)}`);
    return `<path class="${cls}" d="M${pts.join("L")}" stroke-width="${(weight[cls] ?? stroke).toFixed(2)}"/>`;
  });

  return { svg: paths.join(""), x, y, mid };
}

/** Decodes images before they are used as CSS backgrounds, so the screenshot never races a load. */
export async function preload(urls) {
  await Promise.all(urls.map(async (url) => {
    const img = new Image();
    img.src = url;
    try { await img.decode(); } catch { throw new Error(`image failed: ${url}`); }
  }));
}

/** Resolves when web fonts and every <img> on the page are decoded. */
export async function settle() {
  await document.fonts.ready;
  await Promise.all([...document.images].map((img) => img.decode().catch(() => { throw new Error(`image failed: ${img.src}`); })));
  const faces = [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family.replace(/"/g, ""));
  for (const family of ["Zalando Sans", "Martian Mono"]) {
    if (!faces.includes(family)) throw new Error(`font not loaded: ${family}`);
  }
}

export const MARK = {
  pass: '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.5"/></svg>',
  fail: '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  held: '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg>',
};

// The judge page's mark (docs/index.html): a square split along one fault, offset, with the fault in red.
export const WORDMARK_GLYPH = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 18V8.5L11.5 18z" fill="currentColor"/><path d="M8.5 2H18v9.5z" fill="currentColor"/><path d="M5.6 5.6l8.8 8.8" stroke="#ff5a4e" stroke-width="1.2"/></svg>';
