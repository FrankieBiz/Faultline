export const meta = {
  name: 'faultline-review-panel',
  description: 'Run FaultLine reviewer personas in parallel, have a skeptic refute each one\'s findings, and write one ranked report',
  whenToUse: 'Before a release or submission, or whenever you want independent perspectives (contrarian, fresh eyes, UI, bugs, features, judge) on FaultLine. args: { date, focus?, personas?, maxPerPersona?, out? } or a focus string.',
  phases: [
    { title: 'Review', detail: 'one agent per persona defined in .claude/agents' },
    { title: 'Verify', detail: 'a skeptic tries to refute each persona\'s findings' },
    { title: 'Synthesize', detail: 'dedupe across personas, rank, and write the report' },
  ],
}

// Each persona's role, scope, and rules live in .claude/agents/<file>, so they also work as standalone subagents.
const PERSONAS = [
  { key: 'contrarian', file: 'faultline-contrarian.md' },
  { key: 'fresh-eyes', file: 'faultline-fresh-eyes.md' },
  { key: 'ui-qa', file: 'faultline-ui-qa.md' },
  { key: 'bug-hunter', file: 'faultline-bug-hunter.md' },
  { key: 'feature-scout', file: 'faultline-feature-scout.md' },
  { key: 'judge', file: 'faultline-judge.md' },
]

const opts = typeof args === 'string' ? { focus: args } : (args ?? {})
const selected = opts.personas ? PERSONAS.filter((p) => opts.personas.includes(p.key)) : PERSONAS
if (!selected.length) throw new Error(`No personas matched ${JSON.stringify(opts.personas)}; choose from ${PERSONAS.map((p) => p.key).join(', ')}`)
const MAX = opts.maxPerPersona ?? 8
const out = opts.out ?? `.agents/reviews/${opts.date ?? 'undated'}-panel.md`
const focus = opts.focus ? `\nFocus this pass on: ${opts.focus}. Stay within that scope unless something outside it is critical.` : ''

const SEVERITY = { type: 'string', enum: ['critical', 'high', 'medium', 'low'] }
const FINDINGS = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'Your overall verdict in 2-4 sentences. The judge persona puts its per-criterion scores here.' },
    findings: {
      type: 'array',
      maxItems: MAX,
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          kind: { type: 'string', enum: ['bug', 'safety', 'ux', 'a11y', 'overclaim', 'docs', 'gap', 'idea', 'risk'] },
          severity: SEVERITY,
          location: { type: 'string', description: 'file:line, or "n/a" for ideas that add new files' },
          evidence: { type: 'string', description: 'What you saw or ran that supports this, including the reproduction for bugs' },
          recommendation: { type: 'string' },
          effort: { type: 'string', enum: ['S', 'M', 'L'] },
        },
        required: ['title', 'kind', 'severity', 'location', 'evidence', 'recommendation', 'effort'],
      },
    },
    omitted: { type: 'integer', description: 'How many lower-priority findings you left out to stay within the limit' },
  },
  required: ['summary', 'findings', 'omitted'],
}
const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          index: { type: 'integer' },
          verdict: { type: 'string', enum: ['confirmed', 'plausible', 'refuted', 'already-done'] },
          severity: SEVERITY,
          reason: { type: 'string' },
        },
        required: ['index', 'verdict', 'severity', 'reason'],
      },
    },
  },
  required: ['verdicts'],
}

log(`Panel: ${selected.map((p) => p.key).join(', ')} · up to ${MAX} findings each · report → ${out}`)

const results = await pipeline(
  selected,
  (p) => agent(
    `You are a reviewer on FaultLine's review panel. First read .claude/agents/${p.file}: it defines your role, scope, and rules, and you must follow it exactly. The repository root is the current working directory.${focus}\n` +
    `Other reviewers cover other angles, so stay in your lane. Return at most ${MAX} findings, most important first, and report in "omitted" how many others you left out.`,
    { label: `review:${p.key}`, phase: 'Review', schema: FINDINGS },
  ),
  async (review, p) => {
    const findings = review.findings.map((f, index) => ({ index, ...f }))
    log(`${p.key}: ${findings.length} findings${review.omitted ? `, ${review.omitted} omitted` : ''}`)
    if (!findings.length) return { persona: p.key, summary: review.summary, omitted: review.omitted, findings }
    const checked = await agent(
      `First read .claude/agents/faultline-verifier.md: it defines your role. The repository root is the current working directory.\n` +
      `Check these findings from the ${p.key} reviewer and return exactly one verdict per finding, keyed by its index.\n\n${JSON.stringify(findings, null, 2)}`,
      { label: `verify:${p.key}`, phase: 'Verify', schema: VERDICTS },
    )
    const byIndex = new Map((checked?.verdicts ?? []).map((v) => [v.index, v]))
    // Verifiers sometimes return fewer verdicts than findings; give the skipped ones one more pass.
    const skipped = findings.filter((f) => !byIndex.has(f.index))
    if (skipped.length) {
      log(`${p.key}: verifier skipped ${skipped.length}; retrying those`)
      const retry = await agent(
        `First read .claude/agents/faultline-verifier.md: it defines your role. The repository root is the current working directory.\n` +
        `Check these ${skipped.length} findings from the ${p.key} reviewer. Return exactly ${skipped.length} verdicts, one per finding, keyed by its index; an empty list is not acceptable.\n\n${JSON.stringify(skipped, null, 2)}`,
        { label: `verify:${p.key}:retry`, phase: 'Verify', schema: VERDICTS },
      )
      for (const v of retry?.verdicts ?? []) if (!byIndex.has(v.index)) byIndex.set(v.index, v)
    }
    return {
      persona: p.key,
      summary: review.summary,
      omitted: review.omitted,
      findings: findings.map((f) => {
        const v = byIndex.get(f.index)
        // An unverified finding is kept and labeled, never silently promoted or dropped.
        return v ? { ...f, verdict: v.verdict, severity: v.severity, verifierReason: v.reason } : { ...f, verdict: 'unverified', verifierReason: 'The verifier returned no verdict.' }
      }),
    }
  },
)

const panel = results.filter(Boolean)
const missing = selected.filter((p) => !panel.some((r) => r.persona === p.key)).map((p) => p.key)
if (missing.length) log(`No result from: ${missing.join(', ')}`)
const tally = {}
for (const f of panel.flatMap((r) => r.findings)) tally[f.verdict] = (tally[f.verdict] ?? 0) + 1
log(`Verdicts: ${JSON.stringify(tally)}`)

phase('Synthesize')
const synthesis = await agent(
  `You write the FaultLine review panel report. The repository root is the current working directory.\n` +
  `Below is every reviewer's summary and verified findings as JSON. Write a Markdown report to ${out} (create the directory if needed). Do not modify any other file.\n\n` +
  `Report structure:\n` +
  `1. Title "FaultLine review panel: ${opts.date ?? 'undated'}", then which personas ran${missing.length ? ` (no result from: ${missing.join(', ')})` : ''}, the verdict tally, and the total number of findings reviewers omitted for the ${MAX}-per-persona limit.\n` +
  `2. "Fix now": confirmed or plausible critical/high defects (bug, safety, ux, a11y, overclaim, docs, risk).\n` +
  `3. "Worth fixing": the remaining confirmed or plausible medium/low defects.\n` +
  `4. "Feature ideas": confirmed or plausible ideas and gaps, ranked by judge-visible payoff divided by effort, marking which fit before the November 4, 2026 deadline.\n` +
  `5. "Judge's view": the judge persona's scores and top questions, plus each other persona's one-line summary.\n` +
  `6. "Refuted, already done, or unverified": one line each with the verifier's reason, so nothing is silently dropped.\n` +
  `Merge findings that describe the same problem, and list every persona that raised it; agreement between independent personas is a signal worth showing. In each section, mark plausible items as plausible. ` +
  `Each item: a bold title, location, one or two sentences of evidence, the recommendation, effort, and the verdict.\n\n` +
  `Return a plain-text summary of at most 12 lines: counts per section and the top 5 items to act on, each with its location.\n\n` +
  JSON.stringify(panel, null, 2),
  { label: 'synthesize', phase: 'Synthesize' },
)

return { report: out, tally, missing, synthesis }
