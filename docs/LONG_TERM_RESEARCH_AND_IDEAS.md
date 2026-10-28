# FaultLine: long-term research, improvement ideas, and strategic experiments

**Research date:** October 27, 2026.
**Project:** FaultLine, controlled browser QA and verified source repair.
**Purpose:** A substantial research and brainstorming notebook for deciding what to build over the next week, quarter, year, and beyond.
**Research performed by:** GPT-6.1 via Codex; repository inspection and public web research. No other model was called for this research. Model names discussed below describe possible future experiments, not research agents that were used.
**Status:** Recommendations and hypotheses, except where explicitly labeled as repository facts or externally documented capabilities. Nothing in this document establishes customer demand, production readiness, model access, or repair correctness beyond the evidence available.

## Contents

1. [The central opportunity](#1-the-central-opportunity)
2. [What exists and what remains unproven](#2-what-exists-and-what-remains-unproven)
3. [Research method and corrections](#3-research-method-and-corrections)
4. [Users, problems, and product directions](#4-users-problems-and-product-directions)
5. [Competitive landscape and differentiation](#5-competitive-landscape-and-differentiation)
6. [Near-term priorities](#6-near-term-priorities)
7. [Reproduction and diagnosis research](#7-reproduction-and-diagnosis-research)
8. [Repair generation research](#8-repair-generation-research)
9. [Independent verification research](#9-independent-verification-research)
10. [Evaluation and benchmark design](#10-evaluation-and-benchmark-design)
11. [Meta tooling experiments](#11-meta-tooling-experiments)
12. [Runtime, lifecycle, and distributed scaling](#12-runtime-lifecycle-and-distributed-scaling)
13. [Evidence, provenance, and privacy](#13-evidence-provenance-and-privacy)
14. [Inspector and developer workflow ideas](#14-inspector-and-developer-workflow-ideas)
15. [Integration strategy](#15-integration-strategy)
16. [Customer discovery and adoption](#16-customer-discovery-and-adoption)
17. [Economics and resource planning](#17-economics-and-resource-planning)
18. [Large idea catalog: 120 additional possibilities](#18-large-idea-catalog-120-additional-possibilities)
19. [Experiment portfolio](#19-experiment-portfolio)
20. [Roadmap with evidence gates](#20-roadmap-with-evidence-gates)
21. [Failure modes and reasons to change direction](#21-failure-modes-and-reasons-to-change-direction)
22. [Long-horizon bets](#22-long-horizon-bets)
23. [Decisions and questions worth revisiting](#23-decisions-and-questions-worth-revisiting)
24. [Source register](#24-source-register)

## 1. The central opportunity

The strongest long-term hypothesis is that FaultLine can become a trusted verification layer for proposed software repairs. The core deliverable would be a reproducible failure, a narrowly scoped candidate, an independently executed evaluation, and a reviewable evidence packet. A developer should be able to understand what changed, what passed, what was excluded, and how to reproduce the result.

That direction follows the strongest existing parts of this repository: real browser execution, protected business assertions, pinned source provenance, bounded patch policy, durable lifecycle records, isolated candidate execution, and cleanup requirements. It also addresses the most consequential weakness in software automation: a plausible explanation and a green test suite may still leave the intended behavior broken.

A useful product promise to investigate is:

> Bring a failing journey and a proposed fix. FaultLine tells you what the available evidence supports, preserves the evidence, and makes the result easy to review.

This supports several business shapes. FaultLine could generate its own candidates, evaluate patches from external coding tools, serve as a local developer utility, or become an integration attached to CI. These options should share one trusted execution and evidence foundation. There is no need to choose a large hosted platform before learning whether developers value the first useful packet.

### 1.1 A sequence of increasing capabilities

| Stage | Capability | Evidence needed before moving further |
| --- | --- | --- |
| Reproduce | Replay a reported failure in a controlled environment | Stable reproduction with environment and data requirements recorded |
| Explain | Connect observed symptoms to plausible source locations | Diagnosis accuracy on independently labeled cases |
| Propose | Produce a bounded candidate change | Valid proposals across unfamiliar defects |
| Evaluate | Execute protected checks against the exact candidate | Holdout rejection of deliberately incorrect candidates |
| Review | Give a developer an understandable patch and evidence packet | Developers can make faster, accurate decisions |
| Integrate | Attach results to the team's existing workflow | Repeat usage and acceptable setup burden |
| Operate | Run many independent jobs with bounded resources | Recovery, isolation, fairness, and cost evidence |
| Promote | Participate in an existing release workflow | Separate approvals, rollout controls, and operational ownership |

Treat each stage as a capability to earn. Success in a local fixture does not automatically establish the next stage.

### 1.2 Three possible durable advantages

**A library of independently specified business invariants.** Many models can write patches. Teams may value reusable definitions of what a checkout, booking, subscription, or import workflow must preserve. The usefulness depends on domain fit and the cost of configuring those definitions.

**A corpus of repairs paired with trustworthy negative examples.** Rejected candidates, their counterexamples, and subsequent developer decisions could be more valuable than collecting green patches alone. Collection requires explicit project permission, provenance, and separation between customer data and public benchmarks.

**A portable evidence format.** If another developer can validate a result without trusting the Inspector screenshot or a hosted account, the packet becomes useful in reviews, incident retrospectives, and tool comparisons. Adoption of such a format remains a hypothesis.

## 2. What exists and what remains unproven

This baseline comes from [README.md](../README.md), [PROJECT_STATUS.md](PROJECT_STATUS.md), [QUALITY_REVIEW.md](QUALITY_REVIEW.md), [.agents/HANDOFF.md](../.agents/HANDOFF.md), and inspection of the adapter, contracts, oracle, policy, worker, runtime, and database. Historical check counts below are recorded evidence from those files, not a claim that this research session reran their browser experiments.

### 2.1 Repository facts

- The live scenario is `scripted_checkout_repair`: a seeded optional-coupon checkout failure in a Python backend.
- Candidate generation is intentionally specific to that defect. The adapter prompt explicitly names the expected absent-coupon behavior and the file permitted to change.
- The deterministic adapter performs a known source replacement. Its results establish workflow behavior for that seed; they do not measure model reasoning or generalization.
- The default hosted model target is `muse-spark-1.3`. This is a configuration fact, not confirmation of available account access.
- Missing credentials select an explicitly identified deterministic provider. Configured provider failures do not silently fall back.
- Proposals are strict structured objects containing a single-file unified diff and a source hash.
- Existing patch limits include 16 KiB diff, 32 KiB source, and 100 changed lines. These bound the current repair scope.
- Candidate execution uses Linux Bubblewrap. Detached worktrees manage candidate source; they are separate from the process isolation mechanism.
- The trusted browser oracle runs once and records what it observes. It does not repair the test or retry until a passing result appears.
- Durable admission, idempotency, cancellation, deadlines, restart handling, resource ownership, and cleanup quarantine already exist.
- The runtime lease is intentionally a singleton. Multi-worker scheduling is a future design problem.
- The current product produces a verified isolated candidate and downloadable artifacts. It does not deploy application repairs into production.
- Additional scenario references are authored previews. They are not implemented live repair scenarios.

The quality review records 159 backend/script tests, 198 orchestrator tests, 32 runner unit tests, eight Inspector browser tests, seven required isolated-runtime tests, and a deterministic job with 44 candidate assertions. These counts describe that review snapshot and can change with later work.

### 2.2 Unknowns that matter more than feature count

| Unknown | Why it changes the plan | Fastest useful way to learn |
| --- | --- | --- |
| Can the actual Meta provider repeatedly repair unfamiliar defects? | Determines whether generation deserves expansion | Frozen small holdout suite with retained live attempts |
| Do independent checks reject plausible wrong repairs? | Determines whether “verified” provides useful assurance | Deliberately incorrect candidate challenge set |
| Can another developer configure a project? | Determines whether this is usable outside its fixture | Observed setup session on an unrelated repository |
| Will developers inspect the packet? | Determines whether evidence creates value | Timed review exercise with and without packet |
| What permissions will teams grant? | Determines feasible integrations | Discovery around actual repository and telemetry policies |
| Is environment setup the dominant cost? | Determines whether orchestration or inference deserves optimization | Per-stage timing on representative projects |
| Is failure reproduction stable enough? | Determines how much repair evaluation can be trusted | Repeated baseline runs and explicit flakiness classification |

### 2.3 Preserve the successful constraints

Keep the trusted verifier outside the candidate application. Keep source identity attached to the evaluated artifact. Preserve explicit provider identities, unknown token usage, cleanup outcomes, and infrastructure errors. Broader support should be introduced through versioned policy profiles and adapters, with the existing constrained path remaining a useful regression reference.

## 3. Research method and corrections

The research used primary technical documentation, original papers, official vendor documentation, and official event pages. The source register includes retrieval dates, applicability, and limitations. Vendor documentation establishes advertised behavior; it does not establish comparative superiority. Paper abstracts support the limited findings described here; this notebook does not claim a systematic review of every paper or an independent reproduction of published experiments.

The recommendations are original synthesis grounded in the repository and those sources. Numerical targets, customer segments, proposed prices, timelines, and experiment thresholds are planning assumptions unless otherwise identified. No customer interviews, paid inference, hardware benchmarks, or production traffic tests were performed for this notebook.

### 3.1 Corrections to the earlier ideas document

This expanded document replaces an earlier short blueprint. Several of its directions are retained as experiments, with stronger qualifications:

| Earlier claim or implication | Evidence-respecting interpretation |
| --- | --- |
| A guaranteed hackathon-winning MVP | Competition outcome is unknown; the current review identifies substantial evidence gaps |
| Downtime necessarily costs thousands per minute | Impact varies by business; estimate from confirmed incident and transaction data |
| The project already demonstrates live Meta reasoning | Current certified repository evidence describes deterministic workflow runs |
| A challenger eliminates overfitting | Additional tests can expose errors; oracle incompleteness and correlated mistakes remain |
| AST transforms guarantee valid repairs | A bounded transform can reduce formatting or syntax problems; behavior and integration still require execution |
| Kernel events produce deterministic browser reproductions | Some network symptoms can be simulated; many causal details cannot be reconstructed from those signals |
| Signatures establish compliance or non-repudiation | Signatures bind an identity to bytes under a trust policy; they do not establish legal conclusions or complete controls |
| Cached repair patterns yield sub-100ms verified repairs | Candidate lookup can be cheap; fresh execution and state validation still take time |
| Tool-call templates guarantee fast or correct execution | Templates and constrained schemas do not guarantee semantic behavior or latency |
| An enterprise repair platform fits a fixed short timeline | Scope and readiness depend on staffing, integration needs, and measured evidence |

### 3.2 Official event facts and a discovered discrepancy

The official [Meta event page](https://dev.meta.ai/events/global-hackathon) and [Cerebral Valley event page](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon), retrieved October 27, 2026, list November 4 at 9 PM ET as submission time and state that dates may change. Event materials guide the immediate evidence work; long-term ideas remain independent of prize outcomes.

The current Cerebral Valley page lists a **$100 Fireworks offer to selected participants**. The derived [HACKATHON_BRIEF.md](HACKATHON_BRIEF.md) currently says $25. Record the discrepancy here; do not treat either amount as a verified personal credit balance. The preserved webinar artifacts remain immutable. This research task does not change the brief or any protected source file.

## 4. Users, problems, and product directions

### 4.1 Candidate initial users

These are interview hypotheses, not validated market segments.

| Candidate user | Recurring problem to investigate | Useful first deliverable | Likely obstacle |
| --- | --- | --- | --- |
| Small SaaS team with Python APIs | Intermittent business-flow failures are slow to reproduce | Reproduction plus regression packet | Setup time exceeds repair time |
| Agency maintaining many client apps | Repeated debugging and inconsistent handoffs | Portable case archive for a client defect | Every client environment differs |
| Developer reviewing generated code | Patch looks reasonable but intent is unclear | Independent behavior comparison | Existing CI may already be sufficient |
| Open-source maintainer | Bug reports omit reproducible details | Minimal reproducer and candidate evidence | Untrusted code and dependency setup |
| QA engineer with Playwright suites | Failing browser tests lack actionable backend context | Browser-to-request-to-source correlation | Access to backend source and telemetry |
| Platform team supporting coding agents | Each agent reports success differently | Common evaluation and artifact contract | Building internally may seem easier |

An initial focus on Python web applications is consistent with the existing backend and runtime. Expanding immediately into arbitrary languages, mobile apps, databases, and infrastructure would multiply the environment and oracle work before the value proposition is tested.

### 4.2 Product direction A: local verified-repair workbench

A developer supplies a repository, a reproducible browser journey, and a bounded source scope. FaultLine runs locally, proposes or imports a candidate, and creates a packet. Advantages include a direct path from the current architecture, limited need for hosted execution, and a developer who can resolve environment details. Weaknesses include local setup requirements and uneven machines.

**Smallest experiment:** Give an unfamiliar developer a prepared unrelated Python app and instructions. Observe whether they can produce an interpretable packet without intervention. Record every intervention instead of silently fixing setup for them.

### 4.3 Product direction B: independent evaluator for coding tools

FaultLine accepts a patch from any authorized tool or human. It evaluates the patch under a declared scope and outputs a machine-readable verdict with artifacts. This makes candidate generation interchangeable and creates a clear reason to use FaultLine alongside an existing editor.

**Smallest experiment:** Evaluate the same curated patch set through ordinary CI and through FaultLine. Count defects detected only by the independent business checks and measure added runtime and reviewer burden. The outcome could show that better CI configuration alone solves the problem; that is useful evidence.

### 4.4 Product direction C: incident-to-review assistant

An approved observability integration provides a bounded incident summary. FaultLine helps reproduce the problem in an isolated environment and prepares a candidate for review. This fits real operational work but adds privacy, telemetry completeness, state reconstruction, permission, and duplicate-incident problems.

**Smallest experiment:** Use exported, sanitized incidents from a consenting developer. Process files locally before implementing an always-on service or broad integration.

### 4.5 Product direction D: benchmark and verifier infrastructure

A public case format, negative patch corpus, and evaluation runner could support research and tool comparisons. This may create adoption before commercial demand emerges, but maintaining fair benchmarks is ongoing work. A benchmark can attract users who never need a paid repair product.

**Smallest experiment:** Publish only after review: a small, well-documented benchmark release with reproducible cases, known limitations, and environment pins. Measure independent reproduction and useful contributions rather than page views alone.

### 4.6 Working choice

Prioritize A and B as compatible experiments. Keep C as a later integration and D as a possible distribution or research asset. Revisit the choice after observed setup sessions and review exercises. This choice is a proposed strategy, not an architectural migration authorized by writing this notebook.

## 5. Competitive landscape and differentiation

The relevant alternatives already overlap with parts of FaultLine's workflow. It would be inaccurate to describe automated repair, browser monitoring, test healing, or issue-to-PR generation as new categories invented here.

| Alternative | Documented capability | Implication for FaultLine |
| --- | --- | --- |
| Sentry Seer | Issue-fix API includes root-cause analysis, code changes, and PR creation | Investigating an exception and proposing a PR is established product territory |
| GitHub Copilot Autofix | Generates suggestions for code-scanning findings | Source repair already fits repository review workflows |
| Playwright Test Agents | Planner, generator, and healer roles; healer can modify failing tests | Clearly distinguish application changes from test changes |
| Checkly | Browser monitoring and documented check-repair workflows | A failing journey plus an AI repair action is insufficient differentiation |
| BrowserStack Percy | Visual comparisons against approved baselines | Visual evidence alone has existing specialized alternatives |
| SWE-agent and related research tools | Repository navigation, editing, and execution for issue resolution | General agent capabilities have extensive prior art |

Sources: [Sentry Issue Fix API](https://docs.sentry.io/api/seer/start-seer-issue-fix/), [GitHub application card](https://docs.github.com/en/code-security/responsible-use/security-and-quality-ai-features), [Playwright agents](https://playwright.dev/docs/test-agents), [Checkly browser checks](https://www.checklyhq.com/docs/detect/synthetic-monitoring/browser-checks/overview/), [Checkly automatic check repair](https://www.checklyhq.com/docs/resolve/automatic-check-repair/), [Percy visual testing](https://www.browserstack.com/docs/percy/overview/visual-testing-basics), and [SWE-agent paper](https://arxiv.org/abs/2405.15793), retrieved October 27, 2026. These are capability references, not hands-on product comparisons.

### 5.1 A differentiation claim worth testing

“Independent evaluation of an application patch against protected business rules, with exact execution identity and portable browser evidence” is a more specific proposition than “an agent fixes bugs.” It becomes meaningful only if users can see the added value against their existing CI and review process.

A particularly strong demonstration would show two candidates for the same failure. One returns a successful status but breaks coupon semantics or persistence. The other fixes the failure while preserving those behaviors. FaultLine should explain the rejection using observed assertions. This tests the verifier directly and makes the central value understandable.

### 5.2 Questions to ask about alternatives

Ask users which tools they already pay for, how their last generated patch was reviewed, and where verification still required manual work. Do not infer a feature gap merely because a vendor's introductory page omits it. Before making external comparisons, perform an authorized, dated workflow comparison using equivalent cases and clearly identify configuration differences.

### 5.3 Potential partnership paths

FaultLine might consume existing Playwright suites, receive bounded issue context from observability systems, or expose results through repository checks. It could become a specialized verifier inside a broader coding workflow. That possibility reduces the need to build a new editor, incident dashboard, monitoring network, or all-purpose agent runtime.

## 6. Near-term priorities

The immediate constraint is evidence quality. More features will help only if they improve unfamiliar-case performance, developer understanding, or dependable execution.

### 6.1 Priority table

The following scores are planning judgments on a 1–5 scale. They are deliberately coarse. Benefit means expected learning or user value; effort is relative engineering scope; confidence describes confidence in usefulness, not measured success probability.

| Improvement | Benefit | Effort | Confidence | Proposed order |
| --- | --- | --- | --- | --- |
| Retain repeated actual Meta trials | 5 | 2 | High | First, when privately configured access exists |
| Build deliberately wrong candidate cases | 5 | 2 | High | First |
| Add a second unfamiliar, independently specified defect | 5 | 3 | High | First |
| Improve packet explanation and limitations | 4 | 2 | High | Early |
| Observe outside developer setup and review | 5 | 2 | Medium | Early |
| Add portable offline verification | 4 | 3 | Medium | After packet contract is clear |
| Add bounded property tests | 4 | 3 | Medium | After independent expectations exist |
| Add imported patch evaluation | 4 | 3 | Medium | After trusted scope contract |
| Add a hosted worker pool | 3 | 5 | Low | After real concurrent demand |
| Add production traffic promotion | 2 | 5 | Low | Separate later product decision |
| Add graph databases and kernel tracing | 2 | 5 | Low | Only after localization limits are measured |

### 6.2 A practical first cycle

1. Freeze a case definition, provider configuration, prompt version, and attempt budget.
2. Record successful and unsuccessful actual provider runs without changing the prompt between failures.
3. Evaluate a healthy baseline and several plausible incorrect patches.
4. Add one genuinely unfamiliar defect with expectations specified before generation.
5. Create a readable packet from the actual artifacts.
6. Have another developer review the result and explain their understanding.
7. Decide which observed weakness deserves the next change.

This cycle can still be useful when provider access is absent: verifier challenge cases and usability work do not require claiming live inference. Keep model-quality conclusions pending until actual trials exist.

## 7. Reproduction and diagnosis research

### 7.1 Failure signatures with explicit ambiguity

**Idea:** Represent a failure through structured observations: journey step, request route, response classification, exception type, relevant stack location, and a small set of behavioral symptoms. Keep the original bounded evidence attached.

**Why:** Grouping by an exception string alone can merge unrelated problems. Grouping by a full raw traceback can split the same problem whenever identifiers or paths change.

**Experiment:** Create cases where identical exceptions have different causes, and cases where one cause produces different surface messages. Compare simple normalized fingerprints against a model-assisted summary. A useful classifier should preserve uncertainty and avoid collapsing separate defects.

**Small implementation surface:** Existing `Observation`, `ExecutionReport`, and diagnosis stages offer places to attach a versioned fingerprint. Avoid turning free-form explanations into execution authority.

### 7.2 Reproduction as an explicit contract

**Idea:** Each case records required source revision, application data seed, browser version, environment profile, external service substitutes, clock assumptions, and the observable failure predicate.

**Why:** “Run this script” is insufficient when a bug depends on data, timing, permissions, or service state. Reproduction failures should reveal which precondition was unavailable.

**Experiment:** Run the same case after deliberately varying one environment factor at a time. Determine which omissions alter the result and add only necessary metadata. A useful contract is small enough for developers to understand.

### 7.3 Delta debugging of requests and journeys

**Research basis:** The Debugging Book describes reducing failure-inducing inputs through repeated tests. A minimal result is relative to the reduction operations and failure predicate; it need not be the unique global minimum. [Input reduction](https://www.debuggingbook.org/html/DeltaDebugger.html), retrieved October 27, 2026.

**Proposal:** Begin with JSON payload reduction for stable API failures. Remove fields or simplify values while preserving the same diagnosed failure. Later attempt browser-step reduction with dependency constraints: removing login may prevent reaching checkout rather than isolate the defect.

**Acceptance criteria:** The reduced case produces the same failure class, retains required business context, runs repeatedly, and is less expensive to inspect. Track invalid reductions separately from passing reductions. Stop when the reduction budget is exhausted.

**Reason to defer:** A three-step deterministic fixture gains little. This becomes useful when imported cases contain substantial irrelevant state.

### 7.4 Passing-neighbor comparison

**Idea:** Compare a failing input with a nearby passing input under the same environment. Highlight the changed request fields, execution path, and business result.

**Example:** Compare omitted coupon, blank coupon, valid coupon, and unknown coupon without changing cart or shipping data. Expectations must come from the application contract; unknown coupon behavior cannot be generalized across businesses.

**Experiment:** Compare generation with a failure trace alone against generation with a structured passing-neighbor delta. Measure holdout repair quality and token cost. A passing neighbor may expose useful context, but can also anchor the model to an irrelevant difference.

### 7.5 Causal checks before source repair

**Idea:** Classify whether a failure is suitable for a source patch. A timeout caused by an unavailable dependency may need environment recovery, configuration review, or an incident report.

**Experiment:** Mix actual source bugs with port collisions, expired test credentials represented by synthetic fixtures, missing services, and intentionally injected network failures. Measure false source-repair attempts and correct abstentions.

**Benefit:** A useful system should recognize when it lacks enough evidence to propose a patch. Unsupported cases can still produce valuable diagnostic packets.

### 7.6 Telemetry-assisted localization

**Research basis:** OpenTelemetry traces describe distributed work through spans and context propagation. They can help correlate events; they do not capture all UI actions, state, or nondeterminism needed for exact replay. [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/), retrieved October 27, 2026.

**Proposal:** First attach a trusted request identity to browser and backend observations. Next ingest selected spans from a test environment. Rank likely source locations using request route, traceback, imports, and the observed call path. Measure whether this outperforms a simple traceback baseline before building program slicing infrastructure.

### 7.7 Kernel tracing and difficult timing bugs

Keep eBPF as a later investigative option for socket behavior, scheduling symptoms, or process activity that application instrumentation misses. A kernel event is evidence about the event observed. Reconstructing an exact browser reproduction also requires application state and a valid failure predicate.

Start with a synthetic test service and one defined transport failure. Measure whether added tracing changes the diagnosis compared with ordinary logs. Do not introduce privileged collection into the default developer setup without evidence that simpler instrumentation is insufficient.

## 8. Repair generation research

### 8.1 Bounded adaptive proposal loops

The existing limited attempt model is a useful foundation. A future loop should spend another attempt only when new diagnostic feedback exists: a valid counterexample, a precise policy rejection, or an execution failure relevant to the proposed change.

**Proposed policy:** A job has explicit limits for total attempts, wall time, model tokens, candidate executions, and verifier-generated tests. Repeated malformed output should stop with an actionable result. The next attempt receives a bounded gate summary rather than unrestricted verifier internals.

**Experiment:** Compare one attempt, two attempts with feedback, and two independent attempts under the same total budget. Measure reviewed holdout outcomes and cost per accepted repair. Additional attempts can improve coverage while also increasing the chance of finding a patch that overfits visible checks.

### 8.2 Candidate diversity with deterministic selection

**Idea:** Generate candidates that differ in repair mechanism, such as explicit optional-value handling versus a documented default lookup. Evaluate each independently.

**Selection:** Prefer candidates satisfying the declared checks and scope, then use deterministic review aids such as changed surface, complexity, and compatibility findings. Smallest diff is a useful signal but cannot establish correctness.

**Risk:** Several models may produce the same conceptual mistake. Avoid counting model agreement as independent behavioral evidence.

### 8.3 Counterexample-guided repair

**Research basis:** The Nopol overfitting study found that generated tests could help with regression introduction while remaining constrained by the oracle problem for incomplete fixes. These findings concern the studied repair system and benchmark, not current Meta models. [Yu et al., 2018](https://arxiv.org/abs/1810.10614), retrieved October 27, 2026.

**Proposal:** A challenger proposes input cases or properties. A trusted executor runs them. A maintainer-approved specification determines the expected result. Confirmed counterexamples can guide another bounded proposal.

**Crucial boundary:** The challenger does not get to invent the business rule, weaken an assertion, or label its own generated test as authoritative. If the expected result is uncertain, the outcome is a question for the application owner.

**Experiment:** Compare deterministic boundary generation, property-based generation, a challenger model, and their combinations. Track unique confirmed defects found per additional second and per dollar.

### 8.4 Structured edit operations

Raw unified diffs are reviewable and compatible with Git, but malformed hunks create avoidable failures. A future edit interface could express a narrow replacement bound to source hash, function identity, and expected old text.

**Possible progression:** Exact text replacement for a unique bounded span; parsed expression replacement; a small allowlist of concrete syntax transformations; broader edits only if the restricted forms measurably fail useful cases.

**Research basis:** LibCST preserves formatting details and supports codemods, making it a plausible Python editing tool to evaluate. It is not a correctness verifier. [LibCST documentation](https://libcst.readthedocs.io/en/latest/), retrieved October 27, 2026.

**Experiment:** Compare invalid-edit rate, final correctness, human readability, and implementation complexity against current diffs. Always render a reviewable diff and execute the exported result. Reject ambiguous targets and stale source identities.

### 8.5 Localization before sophisticated search

Start with stack frames, route handlers, imported symbols, and bounded neighboring source. Measure localization recall on labeled defects. Only add dynamic slicing, constraint solving, or graph analysis if a meaningful share of unresolved cases is caused by insufficient source localization.

A complex localization engine can fail on dynamic dispatch, metaprogramming, middleware, framework-generated paths, and incomplete traces. An expensive graph is useful only if it changes candidate scope or repair outcomes in a measurable way.

### 8.6 Multi-file repairs

**Prerequisites:** A complete manifest of allowed paths, per-file base hashes, atomic candidate construction, total changed-surface limits, protected tests and policy, dependency controls, and exact export identity.

**First experiment:** Two application files with a small interface mismatch and fixed independent tests. Reject partial application and stale files. Keep dependency and schema migrations outside this first profile.

**Decision rule:** Expand only if the single-file profile blocks valuable cases and the broader profile preserves verifier rejection quality. Arbitrary file access should not be a side effect of making a model more capable.

### 8.7 Learning from prior repairs

Start with a local searchable index of approved cases: failure family, application version, source fingerprint, change summary, and counterexamples. Retrieval suggests candidates; it does not transfer a previous verdict to new source or state.

**Experiment:** Hold out entire repositories and compare no retrieval, text retrieval, and structural retrieval. Ensure the source of every retrieved example is allowed and cannot expose another tenant's code. Record whether retrieval increases mistaken pattern reuse.

## 9. Independent verification research

### 9.1 Make the oracle an owned product surface

Each invariant needs an owner, a version, a rationale, and an applicability condition. “Total never negative” may be universal inside one checkout profile; “unknown coupons fail validation” may be business-specific. Defaults should be explicit and overridable through a reviewed specification change, separate from a repair job.

A future invariant registry could describe the rule, test implementation, relevant input domain, exclusions, and examples that should fail. This helps reviewers understand why an assertion matters and prevents a large unexplained count from becoming a substitute for coverage.

### 9.2 Property-based testing

**Research basis:** Hypothesis stateful testing generates sequences of actions from declared rules. Simple properties may need ordinary generated inputs rather than a state machine. [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html), retrieved October 27, 2026.

**FaultLine experiment:** Start with pure checkout arithmetic and normalization properties, then add stateful order workflows only after their semantics are specified. For example, a non-discounted quantity increase should follow the declared pricing function; invalid requests should preserve the expected order count.

Record the generator version, seed or reproducible example, execution budget, and minimal failure. Generated data expands exploration; it does not supply the expected business answer by itself.

### 9.3 Metamorphic and differential checks

When an exact output is difficult to specify, relationships can still be useful. Reordering equivalent cart entries may preserve a total if order is semantically irrelevant. Repeating a read should not create a new order. A valid representation normalization may preserve the result if documented.

Differential tests compare the candidate with a trusted reference on behavior outside the intended change. A buggy baseline cannot be the reference for the failure being repaired. Document where equality is expected and where it must differ.

### 9.4 Targeted mutation testing

**Research basis:** Mutation tools distinguish killed, survived, uncovered, invalid, and other mutant states. Equivalent mutants and unexercised regions complicate score interpretation. [Stryker metrics](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/) and [mutmut](https://mutmut.readthedocs.io/en/latest/), retrieved October 27, 2026.

**Proposal:** Maintain a small challenge set around a domain's critical rules. Examples include dropping persistence, swapping a boundary operator, changing discount handling, or returning success after bypassing the operation. Execute those challenge patches in disposable environments.

Use findings to improve the oracle. A surviving mutant needs investigation; a raw mutation percentage should not be presented as a probability of repair correctness. Begin offline because running many mutants on every repair can dominate cost.

### 9.5 Contract and schema checks

**Research basis:** Pact verifies integration messages against shared consumer/provider contracts. Schemathesis generates tests from API specifications. These can contribute checks at different layers without replacing business expectations. [Pact documentation](https://docs.pact.io/) and [Schemathesis documentation](https://schemathesis.readthedocs.io/en/stable/), retrieved October 27, 2026.

**Proposal:** Detect candidate changes that silently alter response shape, status semantics, required fields, or consumer expectations. Compare a contract gate against existing Pydantic and browser checks to determine its incremental detection value. Generated API cases should run only against authorized isolated targets.

### 9.6 Race conditions and state integrity

Add a future concurrency profile with explicit interleavings: double submit, cancellation after write but before response, duplicate webhook, and worker restart after an external side effect. Tests need observable state and clear idempotency semantics.

A mocked delay can create a useful schedule, but passing one schedule says little about all interleavings. Record the schedule that was exercised. Avoid claiming broad concurrency correctness from a few parallel HTTP requests.

### 9.7 Flakiness and inconclusive outcomes

**Research basis:** Playwright distinguishes first-pass success, flaky outcomes, and failures when retries are enabled. FaultLine should preserve every attempt and the original failure. [Playwright retries](https://playwright.dev/docs/test-retries), retrieved October 27, 2026.

**Proposal:** A diagnostic repeat can estimate whether baseline failure is stable. It should create additional visible evidence, not rewrite the initial result. If baseline and candidate outcomes overlap substantially, classify the comparison as inconclusive and report the limitation.

### 9.8 Static analysis as an additional gate

Evaluate selected Semgrep rules or Meta Code Shield only for a defined language and threat profile. Measure false positives and findings missed by the existing policy. Static scanning contributes another signal; process restrictions and external execution checks still have separate jobs. [Semgrep CI documentation](https://docs.semgrep.dev/deployment/add-semgrep-to-ci), retrieved October 27, 2026.

Code Shield was considered in the earlier blueprint, but its source page was not successfully retrieved in this pass. Its current packaging, language coverage, and maintenance status remain a follow-up research item rather than a verified integration recommendation.

## 10. Evaluation and benchmark design

### 10.1 Build a benchmark that matches the actual product

**Research basis:** SWE-bench introduced repository-level issue resolution and an executable evaluation setting. Its current official site distinguishes several benchmark variants. Those tasks are useful references, but a checkout-specific result should not be compared directly with a published repository-wide score. [SWE-bench paper](https://arxiv.org/abs/2310.06770) and [official benchmark site](https://www.swebench.com/), retrieved October 27, 2026.

Create a separate FaultLine case collection with declared scope. Its purpose is to measure browser-grounded business-flow repair and candidate rejection. Avoid naming a small authored suite in a way that implies external benchmark endorsement.

### 10.2 Separate three evaluation layers

| Layer | What it measures | Suitable examples | Common mistake |
| --- | --- | --- | --- |
| Harness correctness | Whether jobs, gates, artifacts, and cleanup behave correctly | Malformed diff, stale hash, cancellation, missing screenshot | Treating harness tests as model repair successes |
| Verifier discrimination | Whether checks distinguish good from bad candidates | Known correct patch and plausible behavior-breaking variants | Evaluating only patches expected to pass |
| Generation usefulness | Whether a provider proposes acceptable unfamiliar repairs | Frozen defects with independent holdouts | Counting deterministic source substitution as inference |

The existing test suite mostly supports the first layer, with useful evidence for the controlled scenario. Future work should make the other layers explicit.

### 10.3 Suggested case families

Use a mix of already supported semantics and clearly labeled future profiles:

- Optional value normalization and defaults.
- Boundary errors in quantity limits or rounding.
- Invalid input causing unintended persistence.
- Successful response without durable order creation.
- Incorrect coupon applicability or discount basis.
- Response shape mismatch between browser and API.
- Duplicate requests and idempotency behavior.
- Authorization or tenant separation errors in a dedicated reviewed profile.
- External dependency failure that should trigger abstention.
- Timing-sensitive frontend state errors in a later frontend repair profile.
- Multi-file consumer/provider mismatch after that capability exists.
- No-defect controls where proposing a change is undesirable.

Do not activate all families simultaneously. Each needs a reliable setup, a specification, and credible negative candidates.

### 10.4 Holdout policy

Divide development cases from evaluation cases by defect family and repository where possible. Renaming a known coupon bug or changing a literal is a weak test of generalization. Have someone specify evaluation expectations before seeing candidate output.

Keep visible feedback checks separate from final holdout checks. If a final holdout failure is shown to the proposer and used to revise the patch, that case has become development feedback for that run. Rotate or replace the final test accordingly when measuring untouched generalization.

For a small project, a carefully documented set of genuinely different cases is more useful than a large set of trivial near-duplicates. Report that cases were authored by the project if that is how they were obtained.

### 10.5 Suggested reporting fields

| Metric | Definition | Important qualification |
| --- | --- | --- |
| Reproduction rate | Stable reproduced failures / authorized attempted cases | Include environment and unsupported-case counts |
| Proposal validity | Policy-valid proposals / received proposals | Separate transport errors and malformed output |
| Visible-suite acceptance | Candidates passing visible checks / evaluated candidates | Does not establish final correctness |
| Holdout acceptance | Candidates passing untouched holdouts / evaluated candidates | Limited to case distribution and oracle quality |
| Bad-candidate rejection | Incorrect challenge candidates rejected / incorrect candidates attempted | State which kinds of wrong patches were included |
| Healthy-case preservation | Healthy controls completed without unnecessary accepted change | Distinguish model abstention from provider outage |
| Human acceptance | Patches accepted after review / patches reviewed | Review acceptance can still miss defects |
| Clean termination | Jobs with confirmed cleanup / jobs requiring resources | Include cancelled and failed jobs |
| Cost per reviewed accepted repair | Total eligible job cost / reviewed accepted repairs | Include failed attempts and infrastructure cost |
| Time to reviewable packet | Submission to usable complete packet | Report queue and execution components |

Use counts alongside percentages. “Nine of twelve” is easier to interpret than a precise percentage with a small denominator. If zero false accepts are observed in `n` independent representative trials, the rough rule-of-three upper bound is `3/n` at approximately 95% confidence; independence and representativeness are strong assumptions. Ten repeated runs of the same seeded bug cannot establish a broad false-accept rate.

### 10.6 Baselines and ablations

Compare against a simple deterministic repair where applicable, direct single-prompt generation, existing CI alone, and imported human patches. For each enhancement, change one major factor: richer failure context, another proposal attempt, challenger tests, structured edits, or retrieval.

Keep provider, prompt version, case set, and resource budget fixed for comparisons. If a provider changes behind a stable model identifier, record the date and any available version metadata. Report that uncertainty when interpreting historical comparisons.

### 10.7 Benchmark governance

Version cases and verifier policies. Record why a case was excluded or changed. Preserve failed provider attempts and infrastructure failures in raw results while offering separate conditional metrics. Do not drop difficult cases silently.

A future public benchmark should document licensing, provenance, excluded domains, environment requirements, known ambiguous expectations, and procedures for reporting mistaken oracle behavior. A benchmark whose answers can be read from mounted reference files is unsuitable for measuring generation.

## 11. Meta tooling experiments

### 11.1 Capability inventory before provider changes

The [Meta model catalog](https://dev.meta.ai/docs/models), retrieved October 27, 2026, documents hosted Muse models and open-weight options. This is a public catalog snapshot. It does not verify Frankie's account, regional availability, provider quotas, or any particular model-and-feature combination in this repository.

Build a small future capability record containing the exact endpoint, model ID, supported request shape, successful schema probe, observed usage fields, error classifications, date, and account-approved data mode. Keep credentials outside exported results.

### 11.2 Reasoning and context budgets

Compare the currently configured low-effort request with supported higher-effort settings only after confirming the provider contract. Use identical cases and total job budgets. More reasoning could improve diagnosis while increasing latency or cost; the useful outcome is better reviewed repairs per resource budget.

Also compare source-only context, source plus trace, and source plus passing-neighbor evidence. Measure whether longer context helps or adds distraction. A larger advertised context window is not a reason to upload a whole repository.

### 11.3 Hosted model escalation

One possible policy is to use a lower-cost eligible Meta model first and escalate difficult cases to another documented model. This requires measured failure signals and explicit budget limits. Do not switch models simply because a confident explanation sounds persuasive.

The current adapter should remain a simple baseline. An escalation experiment should record the complete job cost and the incremental successes attributable to escalation. If extra inference rarely changes the outcome, improve reproduction or oracle coverage first.

### 11.4 Chat and stateful tool-loop protocols

Meta's [Chat completion documentation](https://dev.meta.ai/docs/protocols/chat-completions), retrieved October 27, 2026, distinguishes the simple message-based endpoint from Responses-oriented tool loops. A future multi-turn agent may need a different integration contract. Keep protocol changes explicit and test supported schema behavior rather than mixing fields from different APIs.

Any tool loop should expose a small capability list: bounded source read, candidate proposal, and approved verification request. The control plane decides whether a request is admitted. Tool output is untrusted evidence, even when formatted as a structured object.

### 11.5 Multimodal diagnosis

A screenshot or short browser clip could help diagnose a UI state defect that text logs miss. It is a weak source for exact prices, hidden persistence, or authorization behavior.

**Experiment:** Compare DOM/accessibility-tree context against screenshot context on a small visual defect set. Check whether the model identifies the correct affected element and whether the resulting patch passes deterministic behavior and accessibility checks. Keep image input only if it adds measurable value.

### 11.6 Open-weight and local execution

Self-hosted inference could support offline development or restricted-data workflows. It adds hardware sizing, model license review, server maintenance, update discipline, and performance variation. Open weights alone do not establish private processing if the deployment sends telemetry or uses external services.

**Experiment:** Run a frozen case set on one actually available local or partner-hosted model. Report wall time, memory use, proposal validity, holdout results, and total operating burden. Respect current project model-selection rules when scheduling any future runs.

### 11.7 Privacy and data modes

Meta's [pricing documentation](https://dev.meta.ai/docs/pricing-rate-limits), retrieved October 27, 2026, distinguishes Standard and Contributor modes; the latter permits training use under the described terms. Its [ZDR documentation](https://dev.meta.ai/help/policies-and-privacy/zero-data-retention) describes separate organizational enablement and feature restrictions. No personal account eligibility was verified here.

A future provider profile should record the data mode approved by the project owner. Reducing token cost by changing privacy terms is a product decision that requires explicit understanding, especially with customer code. Do not silently substitute a Contributor variant.

### 11.8 What would constitute substantive Meta use

A convincing experiment shows actual Meta-generated candidates on unfamiliar cases, measured rejection of bad output, and retained evidence of provider behavior. A second model call, image feature, or elaborate tool graph adds value only when it improves the tested workflow. Avoid adding unrelated generation features merely to increase the number of Meta services mentioned.

## 12. Runtime, lifecycle, and distributed scaling

### 12.1 Keep a narrow runtime interface

A future runtime profile could expose prepare, execute, collect, and reconcile operations, each with explicit identity and bounded outputs. The model adapter should not know how the process namespace or VM starts. The verifier should not trust self-reported application success.

Keep the existing Linux profile as the reference implementation. New runtimes need the same lifecycle and artifact contract, plus a record of profile-specific limits and exclusions.

### 12.2 Isolation options to evaluate

| Option | Documented mechanism | Why consider it | What to measure |
| --- | --- | --- | --- |
| Existing Bubblewrap profile | Configurable Linux namespace and filesystem isolation | Closest to current implementation | Actual mounts, descriptors, resource usage, cleanup |
| gVisor | Userspace application kernel and OCI runtime | Alternative workload boundary for broader hosting | Application compatibility, latency, operational complexity |
| Firecracker | KVM-based microVM execution | Stronger separation for a hosted execution design | Full job startup, image lifecycle, memory, networking, cleanup |
| Customer-owned runner | Executes inside a customer-controlled environment | Keeps source and state within customer boundary | Setup burden, result identity, upgrade and support model |

Sources: [Bubblewrap](https://github.com/containers/bubblewrap), [gVisor](https://gvisor.dev/docs/), and [Firecracker](https://firecracker-microvm.github.io/), retrieved October 27, 2026. Published mechanism descriptions do not certify a future FaultLine configuration. Measure complete workloads rather than copying advertised startup figures into product promises.

### 12.3 Aggregate resource accounting

The current review identifies per-process limits rather than an aggregate job quota. Before increasing parallelism, evaluate cgroup-based CPU, memory, process, and I/O accounting for the whole owned process tree. Availability depends on host delegation and deployment configuration. [Linux cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html), retrieved October 27, 2026.

A future resource receipt could report peak memory, CPU time, process count, disk/artifact bytes, and termination reason. Candidate application and trusted browser costs should remain distinguishable. A browser process can dominate memory even when the Python candidate is small.

### 12.4 Separate control and execution capacity

When demand justifies it, place durable job admission and evidence metadata in a control service, and send jobs to isolated workers through a narrow protocol. Workers need an ownership token, a source identity, an expiry, and a bounded resource allocation.

Do not interpret worker silence as success. On lost contact, the control plane should preserve uncertainty and reconcile owned resources before considering retries or releasing quarantine.

### 12.5 Leases and stale workers

A distributed lease needs a fencing concept: an old worker that resumes after losing ownership must be unable to finalize a new owner's job or publish a trusted result under that identity. A monotonically increasing lease epoch is one possible design.

Exercise worker restart, late heartbeats, delayed messages, duplicated task delivery, cancelled job completion, and partial artifact upload. “Exactly once” is an unsafe shorthand for external work. Prefer idempotent operations and explicit reconciliation of side effects.

### 12.6 Database evolution

SQLite remains reasonable for the current local singleton. Its WAL mode has same-host constraints and does not turn the application into a distributed scheduler. [SQLite WAL documentation](https://www.sqlite.org/wal.html), retrieved October 27, 2026.

Consider PostgreSQL when actual multi-process or multi-host coordination requirements justify it. Row locks or advisory locks are tools whose correctness still depends on application transaction design. [PostgreSQL locking](https://www.postgresql.org/docs/current/explicit-locking.html), retrieved October 27, 2026.

A migration should preserve case identity, idempotency semantics, event ordering, recovery behavior, and historical result interpretation. Avoid migrating merely because a projected architecture diagram would look larger.

### 12.7 Workflow engine adoption

Temporal offers durable workflow execution and replay concepts. It may become useful for long-running integrations, waits, and recovery across services. [Temporal workflow execution](https://docs.temporal.io/workflow-execution), retrieved October 27, 2026.

First document observed lifecycle failures and operating burden with the existing worker. Compare the cost of fixing them locally with adopting another service. A durable orchestration engine does not automatically provide safe candidate execution or idempotent external side effects.

### 12.8 Capacity planning

Use measured service time, browser memory, queue arrival rate, and artifact size. Start with a fixed worker count and per-project admission limits. Reserve capacity for reconciliation and cancellation so overload does not prevent cleanup.

Google's overload guidance provides a useful basis for bounded admission and graceful degradation. [Handling overload](https://sre.google/sre-book/handling-overload/), retrieved October 27, 2026. For FaultLine, a queued or declined job with a clear reason can be preferable to admitting work that cannot finish inside its budget.

### 12.9 Preview environments and build reuse

Cache dependencies and immutable base application images keyed by lockfile, runtime profile, architecture, and source identity. Candidate overlays must be fresh. Never reuse cookies, orders, writable directories, or evidence identities across cases.

Measure browser startup, application startup, build time, and actual test time separately. Warm workers can lower latency while making contamination harder to detect. Add cross-case isolation probes before relying on warm reuse.

### 12.10 Production promotion as a distinct later decision

A future release integration should consume the organization's existing approval, staging, rollout, and rollback process. A test-passing candidate would be one input to that process.

Canary deployment exposes a bounded population to a change; shadow execution duplicates work while keeping responses out of the user path. Both require careful treatment of state and external side effects. Google's [canary guidance](https://sre.google/workbook/canarying-releases/), retrieved October 27, 2026, supports staged evaluation, not a universal traffic percentage.

The first useful experiment is an isolated staging workflow with synthetic data and intercepted external effects. Live request duplication needs a separate design for payments, messages, emails, webhooks, and irreversible writes. No such deployment is implemented or authorized by this brainstorming document.

## 13. Evidence, provenance, and privacy

### 13.1 A portable case packet

A future packet should contain a manifest, a concise human summary, declared policy scope, baseline and candidate results, the reviewable diff, and the minimum artifacts required to inspect the claim. Large browser traces can be optional downloadable members with explicit hashes.

Suggested manifest fields:

| Group | Proposed contents |
| --- | --- |
| Identity | Packet schema version, case ID, job ID, execution IDs, creation time |
| Source | Repository identifier appropriate for the audience, pinned revision, base hashes, candidate hashes |
| Environment | Runtime profile, interpreter/browser version, dependency lock digest, fixture identity |
| Generation | Provider/model identity, prompt template version, actual usage if known, attempt history |
| Evaluation | Verifier version, assertion IDs, observed results, held-out status, exclusions |
| Lifecycle | Deadlines, cancellation status, resource receipt, cleanup outcome |
| Artifacts | Relative path, media type, size, digest, sensitivity label |
| Trust | Issuer identity, optional signature metadata, trust-policy reference |

A manifest must distinguish an assertion result from an artifact's integrity. A valid screenshot hash says the file matches a digest; it does not say the checkout stored an order.

### 13.2 Offline verification

A future command could validate packet schema, paths, sizes, and digests without executing candidate code. A separate explicit operation could rerun the case in an approved environment. Keep these operations distinct in the CLI and result language.

**Experiment:** Export a packet, move it to a clean machine, and ask another developer to inspect integrity and reproduce the result. Include corruption, missing artifact, incompatible schema, and untrusted issuer controls. This is a proposed future experiment, not a test performed in this research task.

### 13.3 Attestations and signatures

SLSA describes supply-chain assurance levels and provenance formats. in-toto provides a framework for recording supply-chain steps. Sigstore supports artifact signing and verification workflows. These are relevant foundations for a future signed result format. [SLSA v1.2](https://slsa.dev/spec/v1.2/), [in-toto](https://in-toto.io/), and [Sigstore blob signing](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/), retrieved October 27, 2026.

Begin with a precise statement such as “this issuer records that these bytes were evaluated with this policy.” Define the verifier's trusted issuer and identity policy. A signed inaccurate report remains inaccurate. Compliance claims require separately established controls and assessment; an attestation format alone cannot supply them.

### 13.4 Evidence minimization

Browser traces, screenshots, URLs, payloads, and logs can contain personal data, cookies, and proprietary source. Redact before provider submission and before sharing. Preserve a record that redaction occurred, its policy version, and any resulting limitations.

OpenTelemetry's guidance makes clear that sensitive-data handling depends on application context. [Handling sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/), retrieved October 27, 2026.

**Proposed approach:** Default to synthetic data; collect approved fields; classify artifact sensitivity; avoid cookie and authorization capture; keep public replay export as a separate reviewed operation. Hashing low-entropy personal values should not be treated as anonymization.

### 13.5 Retention and deletion

Give each artifact class a proposed retention rule: short-lived execution scratch, longer-lived diagnostic packet, and explicitly retained benchmark data. Track references so deleting a packet does not leave a trace or thumbnail accessible elsewhere.

Do not put sensitive payloads into immutable public logs. A content digest can preserve integrity relationships without publishing the content, although whether even that digest is appropriate depends on the data and threat model. Privacy requirements should shape provenance design before a public evidence service exists.

### 13.6 Honest evidence freshness

Display whether a packet reflects current source, a previous revision, or a historical environment. A patch that passed last week can become stale after dependency, policy, or data changes. An explicit “not evaluated on current revision” status is more useful than an undated green badge.

### 13.7 Tampering and partial artifacts

The packet verifier should reject path traversal, duplicate ambiguous paths, digest mismatch, unexpected media type, unsupported schema, and missing required artifacts. Artifact collection errors need a visible outcome. A future hosted service also needs authorization for every artifact request, including thumbnails and redirected downloads.

The current code already checks several artifact and execution identities. Expand its contract when the supported packaging surface expands; do not replace working checks with a new unsigned summary generated by a model.

## 14. Inspector and developer workflow ideas

These are product concepts, not a frontend implementation plan.

### 14.1 Organize the interface around a decision

The first screen for a completed job should answer: what failed, what changed, what was checked, what remains uncertain, and whether cleanup completed. Detailed logs and model explanations can remain available below those facts.

An explanatory sentence might read: “The candidate completed the checkout journey and preserved the listed pricing and persistence checks in the isolated fixture. Authorization and production behavior were outside this evaluation.” Populate it from the actual scope and results.

### 14.2 Compare baseline and candidate by assertion

Show each meaningful business rule with baseline observation, candidate observation, and expected behavior. This is more useful than a count that grows whenever assertions are split into smaller checks.

**Experiment:** Ask developers to identify whether a candidate is suitable for review using either the comparison or a conventional pass/fail log. Record accuracy and time. Attractive presentation that increases incorrect confidence is a product regression.

### 14.3 Replay actual evidence

Playwright's Trace Viewer supports inspection of recorded traces, including the browser's actions and associated context. [Trace Viewer](https://playwright.dev/docs/trace-viewer), retrieved October 27, 2026. A future Inspector can link actual trace artifacts to assertion results and request identities.

Use real timestamps for measured steps. An edited video may compress waiting for presentation, but should label cuts and retain access to the unedited execution record. Avoid progress indicators that imply elapsed-time certainty when the stage duration is unknown.

### 14.4 Make uncertainty visible

Provide explicit states for unsupported case, model unavailable, baseline unstable, candidate rejected, verification incomplete, artifact incomplete, cleanup failure, and historical result. A user should not need to inspect raw JSON to discover that success referred only to a previous runtime profile.

For a model explanation, label the text as a proposed diagnosis. For measured assertions, link to their observations. This keeps the interface understandable without blending generated narrative with executed evidence.

### 14.5 Reviewer workspaces

Potential additions include saved review notes, a list of unresolved questions, links to changed source spans, and a decision record tied to the packet identity. Comments should not silently change the verifier's expected behavior.

A future rule-change request could show why an invariant is disputed and route that question to its owner. Resolving the rule would create a new policy version and require reevaluation.

### 14.6 Accessibility and motion

Use keyboard-operable controls, visible focus, clear labels, readable diff contrast, and announcements for significant status changes. Avoid repeatedly stealing focus or forcing users to follow animated updates.

Playwright documents automated accessibility checks and the need for complementary manual assessment. [Accessibility testing](https://playwright.dev/docs/accessibility-testing), retrieved October 27, 2026. A future accessibility gate should report its checked rules and exclusions rather than claiming full conformance from a scan.

### 14.7 Public replay as a distinct export

A read-only replay could be the earliest shareable product surface. Export a reviewed, sanitized packet into a static presentation. Keep active execution, mutable controller endpoints, private source, and runtime credentials outside that export.

Measure whether viewers can explain the actual value after one replay: a bad candidate was rejected for a concrete reason, and an acceptable candidate passed a defined evaluation. A public replay should also identify whether inference was live, recorded, or deterministic.

## 15. Integration strategy

### 15.1 Sequence integrations by value and permission

| Proposed integration | First useful capability | Why start there | Later complication |
| --- | --- | --- | --- |
| Local CLI | Import patch, run approved case, export packet | Fits current local execution | Packaging and environment portability |
| CI artifact | Attach packet to an existing job | Small outward-facing surface | Permissions and artifact retention |
| GitHub status/check | Link exact commit to an evaluation result | Familiar review location | App permissions and stale result handling |
| Issue import | Read selected issue metadata | Tests context quality before automation | Untrusted issue text and private data |
| Observability export | Process a sanitized incident file | No continuous ingestion required | Mapping telemetry to reproducible state |
| Hosted integration | Receive authorized webhooks and schedule work | Useful after repeat demand | Deduplication, abuse, tenancy, and quotas |
| Release integration | Hand candidate to existing staging process | Preserves established ownership | Rollout and irreversible effects |

### 15.2 GitHub details

The GitHub Checks API associates a check run with a specific commit and documents integration permissions. Webhook validation uses the configured secret and signature verification. [Check runs](https://docs.github.com/en/rest/checks/runs) and [webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries), retrieved October 27, 2026.

A future integration should deduplicate deliveries, bind the packet to the evaluated SHA, and invalidate assumptions when a branch moves. It should not accept instructions embedded in an issue, PR body, or webhook field as authority to change execution permissions.

### 15.3 CI trust boundaries

GitHub documents risks from untrusted code executed in privileged workflow contexts. [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use), retrieved October 27, 2026.

A future candidate evaluator should receive no repository publishing credential or production secret. A separate trusted integration can publish a bounded result after checking the evidence. Dependency caches, generated artifacts, and fork contributions also need a clear trust policy.

### 15.4 Idempotency across external services

Stripe's documentation illustrates a concrete provider's idempotency semantics, including behavior for retries. Those semantics are provider-specific. [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests), retrieved October 27, 2026.

For FaultLine integrations, define the operation identity and retry behavior explicitly: creating a job, publishing a check, opening a draft PR, or updating an artifact reference. If a request times out after a side effect, reconcile before retrying with a new identity. A webhook delivery ID is not automatically the identity of the underlying business incident.

### 15.5 Standards before adapters everywhere

Stabilize the case, candidate, execution, and packet contracts before writing many integrations. An adapter should translate an external service's data into the same bounded internal representation. Service-specific fields should not leak into every core lifecycle record.

## 16. Customer discovery and adoption

### 16.1 Discovery goals

Learn whether the expensive work is reproduction, diagnosis, patch authoring, verification, review, or environment setup. FaultLine currently addresses several steps, but a user may need only one of them.

A useful first research cohort could include six to ten developers across two candidate segments. That is a planning suggestion, not a statistically representative survey. Choose people with recent concrete defects and permission to discuss sanitized examples.

### 16.2 Interview prompts

1. Describe the last business-flow bug that reached your team.
2. How was it detected, and who first reproduced it?
3. Which information was missing from the initial report?
4. How long did environment setup take compared with changing source?
5. Which tests or checks would have caught the defect earlier?
6. What made reviewers comfortable accepting the fix?
7. Have you rejected a generated patch that passed CI? Why?
8. Which source, logs, and data could an external tool receive?
9. What would prevent installing a local runner or repository app?
10. Which existing tool would you compare this workflow against?
11. Who owns the budget for reducing that work?
12. What evidence would justify trying it on a second incident?

Ask for actual workflows and artifacts before showing a product pitch. A positive reaction to a demo is weaker evidence than allowing a real case, completing setup, or returning with another defect.

### 16.3 Concierge pilot

Work with a consenting developer on one sanitized historical bug. Manually prepare the environment where necessary, while logging that labor. Produce a packet and observe their review. Repeat on a second case without assuming that one successful session validates general applicability.

Track developer effort, operator effort, unsupported requirements, evidence used in the decision, and whether the developer wants to repeat the workflow. A high-quality packet that requires hours of hidden setup may support a service business before a self-serve product.

### 16.4 Adoption friction to measure

Potential blockers include Linux requirements, browser installation, running dependencies, writing a reliable test, defining expected behavior, obtaining telemetry access, repository permissions, artifact sensitivity, and explaining a rejection. Each should be measured through observed setup sessions.

A “time to first packet” metric needs a clear starting point. Starting after someone has already built the fixture hides a major source of user effort. Record both end-to-end setup time and repeated-use time.

### 16.5 Distribution experiments

Possible channels include a technical case study, a reproducible verifier challenge, a small open-source CLI, or a public evidence replay. Prepare materials from real cases and label authored fixtures. Publishing, contacting people, and sending messages remain separate actions requiring the relevant authorization.

Useful outcomes are independent case reproduction, issues that improve the tool, repeat use, and users who contribute a suitable failure. Social impressions alone do not show product value.

### 16.6 Monetization hypotheses

Potential pricing units include project subscription, runner capacity, evaluation minutes, or a bounded team plan. Per-success pricing creates disputes around what counts as success and may reward low-risk cases. Per-token pricing is easy to meter but poorly matches user value. Per-seat pricing may undercharge automated heavy usage.

Begin by measuring total serving and support cost. Then test clear hypothetical offers during discovery. No price in this notebook is based on demonstrated willingness to pay, and this research does not establish revenue projections.

## 17. Economics and resource planning

### 17.1 Measure the complete cost of a useful result

For a job, use:

`job_cost = inference + execution_compute + artifact_storage + transfer + allocated_operations`

For a pilot, separately track human setup and support time. For a product, include unsuccessful jobs, provider retries, idle capacity, abandoned uploads, and cleanup work. Free credits can reduce cash spend during experiments while leaving the underlying unit cost unchanged.

Define “accepted repair” carefully: visible-suite pass, holdout pass, developer approval, and production incident resolution are different events. Choose the denominator appropriate to the decision being made.

### 17.2 Illustrative token arithmetic

The Meta pricing page retrieved October 27, 2026 lists Standard Muse Spark input at $1.25 and output at $4.25 per million tokens. It lists different rates for cached input and Contributor mode. This is a dated public price snapshot, not an account quote or evidence of incurred usage. [Meta pricing](https://dev.meta.ai/docs/pricing-rate-limits).

With **hypothetical** 8,000 uncached input tokens and 1,500 output tokens:

`8,000 / 1,000,000 × $1.25 + 1,500 / 1,000,000 × $4.25 = $0.016375`

That is about 1.64 cents of token charges for this invented request shape. It excludes other calls, unreported billable categories, infrastructure, retries, storage, and labor. Actual request usage and current billing terms must determine real cost.

This example suggests a question to measure: will execution and setup dominate token cost for small cases? The answer could change with larger contexts, more attempts, different models, or expensive verifier suites.

### 17.3 Capacity example

Assume, for illustration, 30 submitted jobs per hour and an average occupied worker time of three minutes. Little's law gives average in-service work of:

`30 jobs/hour × 0.05 hour/job = 1.5 jobs`

This does not mean two workers guarantee low queue latency. Burstiness, variance, long-tail jobs, maintenance, and desired utilization matter. Measure percentiles and arrival patterns before sizing a service. A singleton local runner may be adequate for an individual developer even if a hosted team service would need a queue.

### 17.4 Storage example

Assume, for illustration, 500 daily jobs with a 15 MB retained packet each. That is 7.5 GB per day and 225 GB over 30 days before replication, metadata, versioning, or transfer. Trace retention policy and deduplication can change costs more than small prompt optimizations.

These values are capacity exercises, not observed FaultLine traffic or artifact sizes. Instrument actual packets before using them in budgets.

### 17.5 Value estimation without generic outage claims

A customer's value estimate can include measured developer time saved, fewer repeated review cycles, avoided support escalation, or a reduction in confirmed recurrence. If estimating transaction impact, use that business's eligible traffic, failure rate, recovery duration, and transaction contribution assumptions.

Show ranges and uncertainty. Do not present gross checkout value as recovered profit, attribute every recovery to FaultLine, or borrow a generic downtime-per-minute number as if it describes a small application.

### 17.6 Optimization order

First avoid unnecessary jobs through deduplication and suitability checks. Then improve environment reuse without state leakage. Next reduce repeated expensive verification through safe test selection, while retaining required gates. Optimize model context and routing after measuring where the budget goes.

Caching should accelerate immutable preparation or candidate discovery. A cached historical verdict cannot establish that a new candidate on a new environment still passes.

## 18. Large idea catalog: 120 additional possibilities

This catalog intentionally explores broadly. Every entry is a proposal, not an implemented feature. **Now** means suitable for the next learning cycles; **Next** means after the current verifier and usability gaps improve; **Later** requires additional infrastructure or demonstrated demand; **Research** means unresolved feasibility or value. Priorities are judgments, not measured rankings.

### 18.1 Reproduction and incident intake

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I001 | Case intake checklist that names missing preconditions | Give incomplete reports to developers and measure whether the checklist reduces clarification rounds | Now |
| I002 | Failure predicate editor with concrete examples | Specify one failure through assertions and compare it with vague natural-language descriptions | Next |
| I003 | Payload simplifier preserving the diagnosed exception | Reduce one large synthetic request; count invalid reductions and repeated reproduction rate | Next |
| I004 | Browser journey dependency annotations | Mark actions required for authentication or state; test safe step removal | Later |
| I005 | Sanitized HAR-to-case importer | Import an approved synthetic capture and identify which state still cannot be reconstructed | Next |
| I006 | Console and HTTP event correlation | Match a visible browser error to one request and backend observation using trusted IDs | Now |
| I007 | Reproduction stability report | Repeat fixed cases under unchanged conditions and preserve every result | Now |
| I008 | Environment mismatch explanation | Deliberately vary browser/runtime versions and check whether the packet identifies the mismatch | Next |
| I009 | Passing-neighbor generator | Propose nearby valid inputs and validate them against an owned specification | Next |
| I010 | Unsupported-cause classifier | Mix source defects and environment failures; count incorrect patch attempts | Now |

### 18.2 Diagnosis and context selection

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I011 | Stack-frame relevance ranking | Compare top-ranked locations with maintainer-labeled defective functions | Next |
| I012 | Context ablation report | Remove each context category and measure repair outcomes on the same cases | Now |
| I013 | Source slice budget inspector | Show what was included and excluded from a proposal request without exposing credentials | Next |
| I014 | Exception-to-domain glossary | Map common technical failures to plain explanations reviewed by a developer | Next |
| I015 | Request-state snapshot contract | Record only the synthetic state needed to replay one workflow | Next |
| I016 | Dynamic call-path sampler | Compare simple traceback localization with instrumented call paths on difficult cases | Later |
| I017 | Dependency-edge lookup | Add static imports to context and measure whether localization improves | Next |
| I018 | Contradictory evidence detector | Present conflicting logs and assertions and require an inconclusive diagnosis | Next |
| I019 | Diagnosis confidence calibration | Compare stated uncertainty with independently labeled causes across cases | Research |
| I020 | Human source-location hint | Let a maintainer supply a bounded hint and measure benefit relative to extra context | Now |

### 18.3 Candidate construction

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I021 | Imported patch evaluation | Evaluate a human-authored patch through the existing controlled scenario | Next |
| I022 | Exact-span replacement format | Compare malformed-edit rates with unified diffs under equal budgets | Next |
| I023 | Concrete syntax transform prototype | Implement one bounded transformation in a disposable experiment and inspect formatting preservation | Research |
| I024 | Candidate diversity classifier | Group proposals by mechanism and determine whether multiple calls add real diversity | Next |
| I025 | Patch scope budget explanation | Display why a proposal exceeds its allowed paths or changed surface | Now |
| I026 | Abstention quality benchmark | Include healthy and unsupported cases and count unnecessary proposals | Now |
| I027 | Stale-source repair refusal | Change the base between generation and application and confirm a clear refusal | Now |
| I028 | Candidate dependency-change report | Detect when a proposal would require unsupported imports or dependencies | Next |
| I029 | Semantic change summary | Compare generated summaries with the actual diff and flag unsupported claims | Next |
| I030 | Two-file repair profile | Evaluate a tiny interface mismatch with atomic application and independent tests | Later |

### 18.4 Oracle strength and adversarial evaluation

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I031 | Wrong-patch tournament | Submit several plausible shortcuts and measure independent rejection | Now |
| I032 | Persistence omission challenge | Make the endpoint return success while skipping storage; verify that readback catches it | Now |
| I033 | Coupon semantics challenge | Preserve happy-path status while changing discount behavior; observe which assertions fail | Now |
| I034 | Boundary-value matrix | Cover empty, null, omitted, whitespace, extreme quantity, and malformed types according to contract | Now |
| I035 | Metamorphic cart tests | Check order-independent pricing only where the specification declares equivalence | Next |
| I036 | Stateful order model | Generate create/read/retry sequences with a separately specified expected state | Next |
| I037 | Targeted mutation report | Mutate critical behavior offline and review surviving cases individually | Next |
| I038 | Verifier tamper challenge | Attempt to alter test inputs, expected outputs, or reported verdicts through the candidate surface | Next |
| I039 | Hidden test rotation policy | Rotate evaluated case families after feedback exposure and document why | Next |
| I040 | Oracle dispute workflow | Let a reviewer challenge an expectation and require a new policy version to change it | Later |

### 18.5 Benchmark quality and measurement

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I041 | Public case-card template | Document setup, expected behavior, provenance, and exclusions for one authored case | Now |
| I042 | Repository-held-out evaluation | Hold out a whole unrelated app and measure setup and generation separately | Next |
| I043 | Defect-family-held-out evaluation | Exclude a semantic bug family from development and test transfer to it | Next |
| I044 | Prompt version registry | Attach a stable version and digest to each experiment result | Now |
| I045 | Budget-matched model comparison | Compare eligible providers with equal total attempt and execution budgets | Next |
| I046 | Reviewer-blinded patch comparison | Hide candidate origin while maintainers judge the same patch set | Next |
| I047 | Failure denominator explorer | Show all submitted, excluded, failed, and successful cases in one result export | Now |
| I048 | Infra-failure accounting | Report environment failures alongside model-quality results without conflating them | Now |
| I049 | Benchmark leakage probes | Check whether solutions or expected outputs are exposed to the candidate or proposer | Next |
| I050 | Longitudinal regression suite | Re-run a frozen set when a provider, prompt, verifier, or runtime changes | Next |

### 18.6 Runtime and lifecycle

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I051 | Aggregate resource receipt | Measure process-tree resources under an appropriately delegated cgroup profile | Next |
| I052 | Crash-at-every-stage campaign | Interrupt controlled jobs at lifecycle boundaries and inspect reconciliation | Next |
| I053 | Artifact-upload interruption handling | Stop collection halfway and require an incomplete-evidence outcome | Next |
| I054 | Workspace contamination probe | Put a synthetic marker in one job and confirm it cannot influence the next | Next |
| I055 | Warm-worker reset contract | Compare cold and reused environments while checking state separation | Later |
| I056 | Runtime profile conformance suite | Apply identical lifecycle requirements to two actually implemented adapters | Later |
| I057 | Cancellation latency budget | Measure how quickly owned resources stop under each stage | Next |
| I058 | Disk-pressure behavior | Fill a bounded disposable artifact quota and inspect failure and cleanup | Next |
| I059 | Parent-loss recovery receipt | Record how a worker handles a vanished controller and preserves uncertainty | Next |
| I060 | Host readiness explanation | Give actionable, exact missing-capability messages before job admission | Now |

### 18.7 Scheduling and large-scale operation

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I061 | Per-project fair queue | Simulate one noisy project and measure wait time for others | Later |
| I062 | Cost-aware admission | Reject jobs exceeding a declared project budget before provisioning | Later |
| I063 | Lease epoch fencing | Resume an old worker after reassignment and reject stale finalization | Later |
| I064 | Duplicate incident coalescing | Submit equivalent incident events and preserve one active work identity | Next |
| I065 | Long-job lane separation | Compare short-job latency with mixed versus separate bounded queues | Later |
| I066 | Resource-aware worker placement | Schedule according to measured browser memory and runtime needs | Later |
| I067 | Queue age and expiry policy | Expire obsolete jobs when their source revision or incident is stale | Later |
| I068 | Reconciliation capacity reserve | Saturate workers and verify maintenance work still completes | Later |
| I069 | Region-local execution | Evaluate data-boundary and latency requirements with a real design partner | Later |
| I070 | Customer-controlled runner mode | Produce a packet with minimal central metadata and observe deployment burden | Later |

### 18.8 Evidence and reviewer experience

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I071 | Assertion-level before/after view | Measure whether reviewers distinguish valid and invalid candidates more accurately | Now |
| I072 | Evidence completeness checklist | Remove a required member and ensure the packet visibly becomes incomplete | Now |
| I073 | Offline digest validator | Verify one exported packet and reject a modified screenshot | Next |
| I074 | Signed packet prototype | Verify issuer policy and tamper rejection on a synthetic archive | Later |
| I075 | Claim-to-artifact links | Link each result sentence to specific observed assertions or files | Now |
| I076 | Uncertainty-first summary | Test whether readers correctly identify evaluated and excluded behaviors | Now |
| I077 | Policy version comparison | Explain why the same patch receives different results under two rule versions | Next |
| I078 | Reviewer annotation export | Preserve notes separately from execution facts in the packet | Next |
| I079 | Sanitized public replay | Export a reviewed real run with explicit provider and scope labels | Next |
| I080 | Packet schema compatibility tests | Read older packets without silently upgrading their trust status | Next |

### 18.9 Domain expansion

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I081 | Subscription change profile | Specify proration and state transitions on a synthetic fixture before repair attempts | Later |
| I082 | Booking inventory profile | Define overselling and cancellation semantics with a dedicated oracle | Later |
| I083 | CSV import profile | Detect dropped rows, wrong types, and partial persistence in an isolated importer | Next |
| I084 | Pagination integrity profile | Verify no omitted or duplicated records across stable pages | Next |
| I085 | Tenant separation profile | Use synthetic identities and an explicit authorization matrix | Later |
| I086 | Webhook idempotency profile | Replay duplicate synthetic events and inspect final state | Next |
| I087 | Time-zone boundary profile | Use fixed clocks and declared calendar semantics for a scheduling app | Later |
| I088 | File upload validation profile | Exercise bounded files and persistence rules inside the approved runtime | Later |
| I089 | Notification intent profile | Send to disposable sinks and verify intended counts and recipients | Later |
| I090 | Frontend stale-state profile | Reproduce a held request with user edits and define the expected state transition | Later |

### 18.10 Privacy and configuration

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I091 | Field allowlist for model context | Feed synthetic sensitive markers and inspect the actual approved payload | Now |
| I092 | Artifact sensitivity labels | Classify trace, screenshot, and log examples and test export restrictions | Next |
| I093 | Provider mode record | Attach an approved data-processing mode without revealing account secrets | Next |
| I094 | Redaction explanation | Tell reviewers which evidence was removed and how that limits interpretation | Next |
| I095 | Retention simulation | Expire a synthetic packet and inspect every referenced artifact and thumbnail | Later |
| I096 | Tenant-scoped retrieval | Seed similar synthetic cases in separate tenants and test access isolation | Later |
| I097 | Public packet export filter | Reject exports containing known synthetic credential or personal-data markers | Next |
| I098 | Policy drift detection | Alert when an environment profile differs from the profile used for prior results | Next |
| I099 | Telemetry capture budget | Cap approved fields and bytes while retaining useful failure context | Next |
| I100 | Customer-owned evidence store | Keep artifacts in a customer destination and measure integration complexity | Later |

### 18.11 Integrations and developer ergonomics

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I101 | One-command fixture doctor | Diagnose dependencies and ports without modifying unrelated resources | Now |
| I102 | Existing Playwright test adapter | Import a small approved test while keeping assertions protected | Next |
| I103 | CI artifact-only integration | Attach one reviewed packet to an authorized workflow without opening PRs | Next |
| I104 | Commit-bound status integration | Show a result tied to the evaluated SHA and handle branch movement | Later |
| I105 | Sanitized incident file importer | Process a local JSON export before adding live API ingestion | Next |
| I106 | Draft PR evidence template | Prepare a local review body with scope, checks, exclusions, and artifact references | Next |
| I107 | Editor jump-to-observation links | Open source locations associated with bounded observed failures | Later |
| I108 | Local case notebook | Save reproducible cases alongside project-owned expectations | Next |
| I109 | Dependency cache diagnostics | Explain cache keys and invalidation when environment setup changes | Later |
| I110 | Extension capability manifest | Describe what an adapter can read, execute, and publish before installation | Later |

### 18.12 Product strategy and research distribution

| ID | Idea | Smallest useful experiment | Horizon |
| --- | --- | --- | --- |
| I111 | Verifier challenge article | Draft a real bad-patch rejection case study and test reader comprehension privately | Now |
| I112 | Independent review study | Ask consenting developers to review a balanced patch set with or without packets | Next |
| I113 | Agency maintenance pilot | Evaluate two sanitized defects from the same consenting maintainer | Next |
| I114 | QA-to-backend handoff pilot | Compare a current bug report with a packet carrying correlated execution evidence | Next |
| I115 | Setup-friction diary | Record every intervention needed by an unfamiliar developer | Now |
| I116 | Feature deletion review | Identify UI and orchestration features that users never use in observed sessions | Next |
| I117 | Benchmark contribution program | Prepare a reviewed case template and measure independently reproducible submissions | Later |
| I118 | Invariant pack exchange | Share synthetic domain rules with clear owners, versions, and licensing | Research |
| I119 | Repair-policy research dataset | Publish only permissioned negative candidates and counterexamples with provenance | Research |
| I120 | Interoperable packet proposal | Test whether two independent tools can emit and consume one minimal evidence format | Research |

### 18.13 How to use this catalog

Choose a small set according to the next uncertainty, then define a fixed-budget experiment. Do not implement the catalog in order. Many entries are mutually competing ways to answer the same question, and some should be abandoned after a short investigation.

A reasonable near-term bundle is I007, I026, I031–I034, I041, I044, I071, I075, I076, and I115. It emphasizes reproducibility, verifier discrimination, honest reporting, and developer understanding before new infrastructure.

## 19. Experiment portfolio

Each experiment below has a concrete output and a reason to stop. Suggested sample sizes and thresholds are planning defaults to revise before starting; they are not empirical findings. Run the highest-information experiments first.

### E01 — Can the actual provider repair unfamiliar cases?

**Question:** Does generation work beyond the known optional-coupon seed?

**Setup:** Freeze a small development set and a separate evaluation set across several defect mechanisms. Use the exact supported provider configuration, explicit attempt budget, protected assertions, and retained artifacts. Keep one known fixture for workflow diagnosis, but report it separately.

**Measurements:** Proposal validity, untouched holdout acceptance, incorrect accepted patches after review, token usage where available, execution time, and cleanup. Include provider and infrastructure failures in raw records.

**Continue when:** The provider produces useful candidates across multiple unfamiliar mechanisms and limitations are understood. **Pivot when:** Success depends on explicitly naming the answer in the prompt or every new case requires bespoke implementation. That outcome would favor imported-candidate evaluation or a narrower domain.

### E02 — Can the verifier reject plausible wrong patches?

**Question:** Does the existing evidence distinguish a behavioral repair from a superficial status fix?

**Setup:** Construct a balanced challenge set: correct fix, crash suppression, skipped persistence, altered pricing, incorrect validation, hardcoded fixture output, and an unrelated change. Ensure each candidate is valid source and reaches the appropriate verification stage where possible.

**Measurements:** Rejection reason, missed defects, misleading success summaries, and developer understanding of the outcome.

**Continue when:** Critical domain shortcuts are rejected with inspectable observations. **Pivot when:** Adding assertions mostly duplicates the candidate's implementation or reviewers disagree about the intended behavior. Resolve the specification before increasing candidate generation.

### E03 — Does the packet improve human review?

**Question:** Does the packet help developers make correct decisions faster?

**Setup:** Prepare several patch reviews with known outcomes. Compare ordinary diff/test output with the same material plus FaultLine evidence. Counterbalance case order and avoid showing the same participant the same solution twice.

**Measurements:** Correct acceptance/rejection, time, uncertainty, facts recalled, artifacts consulted, and unsupported assumptions. A small convenience sample gives directional evidence, not a universal productivity claim.

**Continue when:** Accuracy improves or useful time savings appear without increased false confidence. **Pivot when:** Reviewers ignore the packet, misunderstand scope, or make worse decisions. Simplify explanations and find which evidence they actually need.

### E04 — Which test expansion method is worth its cost?

**Question:** Do boundary generators, property tests, or a model challenger add meaningful detection?

**Setup:** Run the same candidate challenge set under the base oracle and each added method. Keep total generation and execution budgets visible. Independently review newly proposed expected outputs.

**Measurements:** Unique confirmed errors found, invalid generated tests, ambiguous expectations, added latency, and cost.

**Continue when:** A method finds material defects missed by the base suite at acceptable cost. **Pivot when:** Most generated tests are duplicates, invalid, or derive expectations from the buggy implementation.

### E05 — Is structured editing worth maintaining?

**Question:** Does a narrow structured edit format improve useful repair outcomes?

**Setup:** Compare diffs with exact-span edits and one concrete syntax transform on the same supported cases. Include stale source, duplicate target text, comment changes, and unsupported syntax controls.

**Measurements:** Edit validity, final behavior, patch readability, target ambiguity, adapter complexity, and unsupported-case count.

**Continue when:** Overall reviewed success improves enough to justify another edit interface. **Pivot when:** Format validity improves while semantic failures stay unchanged and maintenance grows. The existing diff path may remain the better tradeoff.

### E06 — Can an unfamiliar developer use it?

**Question:** What is the actual setup and interpretation burden?

**Setup:** Start from a clean machine or documented environment with an unrelated supported app. Give only the proposed instructions. Log interventions and allow the participant to describe confusion before helping.

**Measurements:** Time from initial setup to usable packet, active developer time, operator assistance, unclear requirements, and whether the developer can explain limitations.

**Continue when:** Setup can be documented and repeated. **Pivot when:** Every repository requires deep manual environment reconstruction. Consider a narrower runtime profile, customer-owned fixture requirement, or assisted service model.

### E07 — Where does the job spend resources?

**Question:** Is the next optimization in build preparation, browser execution, inference, or evidence handling?

**Setup:** Instrument monotonic per-stage timings and actual bytes/resources for a fixed case collection. Compare cold and safely reused immutable preparation.

**Measurements:** Median and tail latency by stage, CPU, peak memory, artifact size, failure handling time, and cleanup time.

**Continue when:** One intervention reduces complete job cost without weakening coverage or isolation. **Pivot when:** Claimed speed gains come from excluding setup, reducing checks, or reusing contaminated state.

### E08 — Is a second domain reusable?

**Question:** Can the same case and evidence contracts support a different business flow?

**Setup:** Choose one constrained domain such as CSV import or pagination. Specify its invariants before asking for repairs. Reuse the existing runtime and lifecycle wherever possible.

**Measurements:** New trusted code needed, setup labor, number of reusable contracts, oracle disputes, and candidate quality.

**Continue when:** Most infrastructure remains unchanged and users value the result. **Pivot when:** Every domain requires an entirely new product and trusted verifier. Domain specialization may be the right strategy.

### E09 — Can external candidate generation coexist cleanly?

**Question:** Is evaluator-only mode valuable alongside an existing coding workflow?

**Setup:** Import approved patches from a developer or existing tool. Disable internal generation for those runs, preserve origin metadata, and use the same protected checks.

**Measurements:** Workflow friction, defects caught beyond ordinary CI, packet usefulness, and repeat usage.

**Continue when:** Developers return with patches to evaluate. **Pivot when:** They only want ordinary test execution and see no value in independent evidence. Improve integration with their existing CI before building another agent.

### E10 — Does broader isolation justify its operational cost?

**Question:** What runtime is appropriate for the actual hosting model?

**Setup:** Compare the existing profile with one carefully configured alternative on representative authorized workloads. Use the same lifecycle and evidence requirements. Include failure and reconciliation scenarios.

**Measurements:** Compatibility, complete startup and teardown, resource overhead, observable boundary behavior, operating burden, and cost.

**Continue when:** The alternative meets a demonstrated deployment requirement. **Pivot when:** It adds complexity without enabling a needed workload or improving a defined boundary. Published isolation claims do not substitute for configuration review.

### E11 — Does the same customer return?

**Question:** Is there recurring value beyond a novel demonstration?

**Setup:** After a pilot, observe whether the developer brings a second and third suitable case or continues evaluation in their own workflow. Do not count a reminder-driven courtesy session as organic retention.

**Measurements:** Repeat cases, setup reuse, operator support, reasons for non-return, competing tools used, and willingness to allocate an actual budget.

**Continue when:** Repeat usage has a clear value story. **Pivot when:** The problem is too rare, setup is too costly, or another tool solves it sufficiently.

### E12 — Can the evidence be independently reproduced?

**Question:** Does the result travel beyond the original machine and author?

**Setup:** Provide an approved packet and case instructions to another developer on a clean compatible environment. Include one intentionally corrupted packet as a control.

**Measurements:** Integrity validation, reproduced verdict, environment differences, manual fixes, trust-policy clarity, and artifact accessibility.

**Continue when:** Another person can reproduce and explain the result. **Pivot when:** The packet depends on hidden local state or unverifiable assertions. Make the environment and evidence contract more complete before distributing it.

## 20. Roadmap with evidence gates

The horizons below are capacity-dependent planning windows, not delivery commitments. They assume focused work and can overlap where dependencies permit. Completion should be determined by outcomes rather than a calendar date.

### 20.1 Immediate cycle: research into credible evidence

**Focus:** E01, E02, and the smallest version of E03. Preserve the controlled demo, add unfamiliar evidence, and show a meaningful rejection.

**Artifacts:** Frozen evaluation description; raw provider records where access is available; candidate challenge results; an actual packet example; list of unresolved expected behaviors; updated truthful demo narrative when evidence supports it.

**Exit gate:** The team can explain exactly what has been measured and what remains unknown. No public claim depends on an unrecorded run, invented usage, or a generic downtime statistic.

### 20.2 First several weeks: a usable local workflow

**Focus:** Import a candidate, configure a supported case, run protected checks, and export a portable packet. Observe unfamiliar developers using it.

**Artifacts:** Versioned case format; setup doctor; evaluator-only path if useful; packet validator; a few independent case families; minimal reviewer guide.

**Exit gate:** Another developer completes a supported workflow with limited assistance and can identify both a valid rejection and the limits of a passing result.

### 20.3 Following quarter: repeat usage and measured breadth

**Focus:** Pilot repeat usage, compare testing enhancements, and add a second domain only if needed. Introduce integrations that remove observed friction.

**Artifacts:** Pilot logs; stage cost measurements; domain invariant ownership; benchmark version; selected CI or repository integration; reviewed retention and export rules.

**Exit gate:** A defined user repeatedly obtains value, serving cost is understood, and the verifier's weaknesses are documented. Broader generation performance should be reported by case family.

### 20.4 Six to twelve months: operational product, if justified

**Focus:** Supported multi-worker operation or customer-owned runners, according to actual demand and permissions. Strengthen resource accounting, recovery, access boundaries, and artifact management.

**Artifacts:** Runtime conformance results; failure-injection campaign; per-project budgets; tenancy model if hosted; cost and support model; integration permission inventory.

**Exit gate:** The service can handle its declared workload and recover from its documented failures. External review should evaluate any broader execution exposure before claims of enterprise readiness.

### 20.5 Beyond a year: interoperable verification infrastructure

**Focus:** A stable evidence contract, independently contributed cases, reusable domain invariants, and evaluation of candidates across tools. Selective participation in an organization's release process may become useful if requested.

**Artifacts:** Multiple independent producers or consumers of packets; benchmark governance; measured policy quality; demonstrated adoption; domain-specific assurance profiles.

**Exit gate:** The ecosystem or customer value justifies maintaining an infrastructure layer. If it does not, a narrower developer tool can remain a successful outcome.

### 20.6 Proposed work boundaries for future implementation

| Area | Existing repository anchor | Example narrowly scoped future task |
| --- | --- | --- |
| Proposal contract | `shared/contracts/models.py` | Add versioned imported-candidate metadata |
| Provider experiments | `services/repair-orchestrator/app/model_adapter.py` | Record supported experiment configuration without secrets |
| Candidate policy | `services/repair-orchestrator/app/policy.py` | Explain a rejected scope in stable machine-readable terms |
| Lifecycle | `services/repair-orchestrator/app/worker.py` and `database.py` | Preserve evaluation metadata across restart |
| Execution | `services/repair-orchestrator/app/isolated_runtime.py` | Add a measured resource receipt under an approved profile |
| Browser evidence | `tools/browser-runner/src/oracle.ts` and `evidence.ts` | Bind a case manifest to collected artifacts |
| Business assertions | `tools/browser-runner/src/assertions.ts` | Add an independently specified negative-candidate check |
| Review UI | `web/inspector-ui` | Link claims to actual assertion observations |
| Documentation | `docs/` | Publish a dated experiment report with all denominators |

These anchors are a navigation aid, not a request to edit all these files. Read current code and tests before any implementation; this research snapshot can become stale.

## 21. Failure modes and reasons to change direction

### 21.1 The business rule is unknown

A patch cannot be reliably judged when the expected result is disputed. More models may produce more opinions. Prioritize specification ownership and an explicit unresolved result. A product helping teams define and test invariants could prove more useful than autonomous patch generation.

### 21.2 The environment is the real product cost

If reproducing each customer's app requires extensive manual work, a general self-serve service may be impractical. Narrow the supported deployment profile, require customer-provided test environments, or offer assisted onboarding. Measure that labor honestly.

### 21.3 Stronger general agents absorb generation value

If general coding tools become much better at the same defects, FaultLine can still matter if its independent evidence changes acceptance decisions. If it contributes no incremental checks or understanding, the product needs a sharper domain or integration advantage.

### 21.4 Better tests solve most of the problem

A team might add a few business assertions to CI and stop needing FaultLine. That is a real competitive outcome. Investigate whether maintaining shared invariant packs, reproducing incidents, or portable evidence still offers enough value. Avoid building infrastructure whose only purpose is wrapping a test command.

### 21.5 The verifier learns the fixture instead of the domain

Repeatedly tuning against the same seed can improve demonstrations while weakening the meaning of success. Hold out semantic families, include unrelated apps, and review near-duplicate cases. A high acceptance rate on the original optional-coupon bug has limited research value.

### 21.6 The model and checker share the same misconception

When the proposer and test author derive expectations from the same ambiguous prompt, they may agree on the wrong behavior. Use independently specified rules, external observations, and human ownership for disputed semantics. Model diversity alone does not resolve this problem.

### 21.7 Repair attempts amplify an incident

A future always-on integration could create many jobs for duplicate alerts, consume resources, or overwhelm maintainers with PRs. Deduplicate incidents, budget attempts, and separate diagnosis from publication. The current local prototype does not have this operating mode, but the risk should shape later design.

### 21.8 Evidence becomes too large to review

More screenshots, traces, and generated paragraphs can reduce understanding. Observe which artifacts reviewers use. Put concise claim-linked observations first and keep raw material available. The packet's quality should be measured by decisions it supports.

### 21.9 Safety controls reject nearly everything useful

A very narrow policy can make a system dependable on a tiny fixture while preventing valuable repairs. Record policy-blocked opportunities and their required capabilities. Expand through explicit profiles after assessing the actual benefit and boundary implications.

### 21.10 Operational sophistication arrives too early

MicroVMs, graphs, distributed queues, and multiple models can absorb months without proving demand. Every substantial infrastructure change should have a named user need or measured constraint, a comparison baseline, and a reason to stop.

### 21.11 Honest negative results

If an experiment fails, retain the setup, denominator, artifacts where appropriate, and interpretation. Distinguish “this design failed under this setup” from “the entire idea is impossible.” Record failed approaches in handoff notes to avoid repeating them without new evidence.

## 22. Long-horizon bets

These directions are intentionally more speculative. They belong in a research portfolio only after nearer-term value is established.

### 22.1 A verification exchange for generated changes

**Possibility:** Coding tools emit candidate changes and specialized verifiers return scoped evaluations. Developers compare evidence independent of the generator.

**Why it might matter:** Different tools optimize generation, while domain checks and reproducibility remain reusable.

**First proof needed:** Two independent candidate sources use the same evaluator contract without bespoke rewrites. **Reason it may fail:** Integration overhead exceeds the benefit of another layer.

### 22.2 Domain invariant libraries

**Possibility:** Maintainers share versioned, executable definitions of domain behavior for checkouts, imports, billing, scheduling, and messaging.

**First proof needed:** The same library helps several unrelated applications after modest configuration. **Reason it may fail:** Business semantics differ enough that the “library” becomes a consulting questionnaire with little reusable code.

### 22.3 Evidence portability as a standard

**Possibility:** Repair packets become an interoperable artifact recognized by review tools, incident systems, and build services.

**First proof needed:** Another tool can independently consume the packet and verify its limited claims. **Reason it may fail:** Existing CI formats and provenance standards already cover the useful surface. In that case, adopt those formats instead of inventing another.

### 22.4 Repair-policy research

**Possibility:** Evaluate how candidate scope, oracle strength, feedback budgets, and test visibility change false acceptance and useful repair rates.

**First proof needed:** A well-curated negative patch corpus with independent expectations and reproducible experiments. **Reason it may fail:** Results depend too strongly on one fixture or one provider to generalize.

### 22.5 Contract-guided multi-service diagnosis

**Possibility:** A bounded graph of services, messages, and approved contracts helps decide which component should change after a compatibility failure.

**First proof needed:** A small real multi-service case where simple tracebacks and contracts are insufficient. **Reason it may fail:** Partial graphs create misleading precision while ownership and version semantics remain unresolved.

### 22.6 Selective formal verification

**Possibility:** Use solver-backed checks for small pure functions such as arithmetic transforms or finite state transitions, then combine their limited guarantees with runtime evidence.

**First proof needed:** A precisely modeled bounded function where the solver finds a defect missed by ordinary checks at acceptable cost. **Reason it may fail:** Framework behavior, external state, or model assumptions dominate real defects. A proof applies to the model and assumptions actually checked.

### 22.7 Learning to abstain and allocate effort

**Possibility:** Historical outcomes help decide whether to attempt repair, ask for clarification, gather more evidence, or stop.

**First proof needed:** A permissioned dataset with outcomes and reliable cost labels, evaluated on held-out projects. **Reason it may fail:** Biased historical choices make the learned policy overconfident or exclude difficult but valuable cases.

### 22.8 Verification marketplaces and trust

**Possibility:** Independent domain experts maintain verifier packs, and teams choose packs matching their workflows.

**First proof needed:** Clear ownership, licensing, update policy, and liability expectations for one pack that people actually reuse. **Reason it may fail:** Trust and maintenance are harder than distributing code. A marketplace cannot manufacture a correct oracle.

### 22.9 A repair memory with bounded transfer

**Possibility:** Retrieve related successful and rejected repairs to accelerate diagnosis and propose tests.

**First proof needed:** Better held-out results without leaking private examples or copying stale assumptions. **Reason it may fail:** Similar syntax hides different business rules, making retrieval a source of systematic mistakes.

### 22.10 Controlled release participation

**Possibility:** Organizations allow FaultLine to prepare staging candidates and supply evidence to their existing promotion machinery.

**First proof needed:** Repeatable staging-only evaluation with synthetic state, approved side-effect boundaries, and a responsible release owner. **Reason it may fail:** Deployment authority, database changes, and operational accountability are separate problems with limited automation appetite.

## 23. Decisions and questions worth revisiting

### 23.1 Proposed default decisions

1. Keep the current controlled workflow as a regression reference.
2. Treat independent candidate evaluation as a first-class product hypothesis.
3. Prioritize unfamiliar defects and wrong-patch rejection over more scenario previews.
4. Keep test expectations outside repair authority.
5. Preserve failed, inconclusive, and cleanup-failed results in reporting.
6. Make packet scope and freshness understandable to reviewers.
7. Use live provider evidence only when actual authenticated runs are retained.
8. Add infrastructure after measuring a constraint or establishing a deployment need.
9. Treat customer discovery and setup friction as engineering inputs.
10. Review the research after experiments; do not turn this entire notebook into a committed build plan.

### 23.2 Open questions

- Which user can provide a real, sanitized, reproducible case first?
- Which business flow has rules explicit enough for independent verification?
- What additional defect family can the current runtime support with minimal trusted changes?
- How many plausible wrong patches does the current oracle reject, and which does it miss?
- Does a second proposal with feedback outperform an independent second proposal?
- Does model-generated test input add value beyond deterministic boundaries and property generators?
- Which context is actually necessary for generation?
- Can outside developers understand the result without a guided explanation?
- Which artifact is indispensable, and which is noise?
- What fraction of total cost is environment preparation?
- How much customer-specific configuration can a useful product tolerate?
- Is local execution a sufficient long-term business, or do users need hosted coordination?
- Which integrations remove real repeated work?
- Does a public benchmark improve adoption, or divert maintenance effort?
- What evidence would justify supporting production-facing workflows?

### 23.3 Suggested next research note

After completing the first two experiments, create a dated report containing the frozen protocol, raw case counts, provider identity, actual outcomes, known errors, costs, and changed recommendations. Link it from this notebook. Prefer a small truthful report with reproducible negative results to another speculative feature expansion.

## 24. Source register

All web sources below were retrieved **October 27, 2026**. Documentation and vendor capabilities can change. Links establish the narrow facts described in their annotations; the proposals elsewhere in this notebook are research synthesis. Failed fetches are disclosed separately and are not treated as verified references.

### 24.1 Local project evidence

| Source | Why it was consulted | Limitation |
| --- | --- | --- |
| [README.md](../README.md) | Current product scope, runtime, setup, and gate definitions | Project-authored description |
| [HACKATHON_BRIEF.md](HACKATHON_BRIEF.md) | Event context and preserved-source references | Derived summary; Fireworks offer discrepancy documented above |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | Implemented capabilities and outstanding evidence | Snapshot, not current session verification |
| [QUALITY_REVIEW.md](QUALITY_REVIEW.md) | Recorded adversarial findings and verification evidence | Repository review, not external certification |
| [SpecV1-research-notes.md](SpecV1-research-notes.md) | Previous technical research and source trail | Prior dated research, recheck before implementation |
| [.agents/HANDOFF.md](../.agents/HANDOFF.md) | Settled constraints and failed implementation approaches | Handoff state may change |
| [model_adapter.py](../services/repair-orchestrator/app/model_adapter.py) | Actual prompt specificity, provider selection, deterministic fallback | Code inspection, not authenticated provider exercise |
| [models.py](../shared/contracts/models.py) | Strict contracts and lifecycle vocabulary | Current local contract |
| [oracle.ts](../tools/browser-runner/src/oracle.ts) | Browser execution behavior and evidence collection | Controlled scenario implementation |
| [policy.py](../services/repair-orchestrator/app/policy.py) | Bounded candidate policy | Policy is not complete program safety |
| [database.py](../services/repair-orchestrator/app/database.py) | Singleton lease, admission, and ownership | Local coordination profile |
| [isolated_runtime.py](../services/repair-orchestrator/app/isolated_runtime.py) | Execution and resource boundary | Configuration-specific, not a universal containment claim |

### 24.2 Official event and Meta documentation

| ID | Primary source | Supported observation and limit |
| --- | --- | --- |
| S01 | [Meta hackathon page](https://dev.meta.ai/events/global-hackathon) | Public themes and dates; does not verify personal participation or final rules acceptance |
| S02 | [Cerebral Valley event page](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon) | Public timeline and selected-participant partner offers; contains the current $100 Fireworks listing |
| S03 | [Meta model catalog](https://dev.meta.ai/docs/models) | Public model families and documented availability distinctions; account access remains unverified |
| S04 | [Meta Chat completion](https://dev.meta.ai/docs/protocols/chat-completions) | Message-based protocol and guidance distinguishing tool-loop use cases; test exact requested feature combinations |
| S05 | [Meta pricing and limits](https://dev.meta.ai/docs/pricing-rate-limits) | Dated public token prices and Standard/Contributor distinctions; actual billing requires observed usage |
| S06 | [Meta zero-data-retention help](https://dev.meta.ai/help/policies-and-privacy/zero-data-retention) | Separate organizational enablement, exceptions, and feature exclusions; no eligibility claim for this account |

### 24.3 Repair research, evaluation, and testing

| ID | Primary source | Supported observation and limit |
| --- | --- | --- |
| S07 | [SWE-bench paper, 2023/2024](https://arxiv.org/abs/2310.06770) | Repository issue-resolution evaluation design; historical paper results are not current performance estimates |
| S08 | [SWE-bench official site](https://www.swebench.com/) | Current benchmark variants; no FaultLine score or ranking established |
| S09 | [SWE-agent paper, 2024](https://arxiv.org/abs/2405.15793) | Agent-computer interface research; published outcomes depend on its experimental setup |
| S10 | [Yu et al., patch overfitting, 2018](https://arxiv.org/abs/1810.10614) | Generated tests can help with some overfitting while oracle limitations remain; studied Nopol/Defects4J context |
| S11 | [The Debugging Book: input reduction](https://www.debuggingbook.org/html/DeltaDebugger.html) | Failure-preserving reduction concepts; minimality depends on operations and predicate |
| S12 | [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) | Generating action sequences from declared rules; expectations still need specification |
| S13 | [Stryker mutant states and metrics](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/) | Distinct mutant outcomes and measurement definitions; score is not correctness probability |
| S14 | [mutmut documentation](https://mutmut.readthedocs.io/en/latest/) | Python mutation tooling; compatibility and budget need local evaluation |
| S15 | [Schemathesis documentation](https://schemathesis.readthedocs.io/en/stable/) | API-schema-based test generation; schema conformance is narrower than business correctness |
| S16 | [Pact documentation](https://docs.pact.io/) | Consumer/provider contract testing; does not replace all integration checks |
| S17 | [LibCST documentation](https://libcst.readthedocs.io/en/latest/) | Formatting-preserving Python source representation and transforms; semantic correctness is separate |
| S18 | [Playwright Trace Viewer](https://playwright.dev/docs/trace-viewer) | Inspection of actual recorded traces; traces may contain sensitive data |
| S19 | [Playwright retries](https://playwright.dev/docs/test-retries) | Retried/flaky result semantics; retries are not proof of a stable repair |
| S20 | [Playwright Test Agents](https://playwright.dev/docs/test-agents) | Planner/generator/healer prior art, including test repair |
| S21 | [Playwright accessibility testing](https://playwright.dev/docs/accessibility-testing) | Automated scan integration and manual assessment limits |

### 24.4 Existing products and workflow integrations

| ID | Primary source | Supported observation and limit |
| --- | --- | --- |
| S22 | [Sentry Issue Fix API](https://docs.sentry.io/api/seer/start-seer-issue-fix/) | Issue-to-diagnosis/change/PR workflow; not an independent product benchmark |
| S23 | [Sentry Seer PR iteration changelog](https://changelog.sentry.dev/changelog/seer-pr-iteration/) | September 21, 2026 product update on iterating existing PRs; feature availability can change |
| S24 | [GitHub security/quality AI application card](https://docs.github.com/en/code-security/responsible-use/security-and-quality-ai-features) | Documented Autofix capabilities and limitations |
| S25 | [Checkly browser checks](https://www.checklyhq.com/docs/detect/synthetic-monitoring/browser-checks/overview/) | Browser-based monitoring of user journeys |
| S26 | [Checkly automatic check repair](https://www.checklyhq.com/docs/resolve/automatic-check-repair/) | Intent-based check-repair workflow and its documented limits; do not conflate check script repair with application repair |
| S27 | [Percy visual testing](https://www.browserstack.com/docs/percy/overview/visual-testing-basics) | Screenshot comparison and review workflow; visual equality does not establish backend behavior |
| S28 | [GitHub check runs](https://docs.github.com/en/rest/checks/runs) | Commit-bound check integration and permission requirements |
| S29 | [GitHub webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) | Delivery signature validation; deduplication and authorization remain application responsibilities |
| S30 | [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use) | Privileged workflow and untrusted-code concerns; evaluate actual workflow configuration |
| S31 | [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests) | Concrete external API retry semantics; not a universal standard for all providers |
| S32 | [Semgrep CI documentation](https://docs.semgrep.dev/deployment/add-semgrep-to-ci) | Static scanning integration; scanner results are an additional gate |

### 24.5 Runtime, operations, and provenance

| ID | Primary source | Supported observation and limit |
| --- | --- | --- |
| S33 | [Bubblewrap repository](https://github.com/containers/bubblewrap) | Namespace-based execution tool; security depends on invocation and host |
| S34 | [gVisor documentation](https://gvisor.dev/docs/) | Userspace application-kernel boundary and OCI integration |
| S35 | [Firecracker project](https://firecracker-microvm.github.io/) | KVM microVM mechanism; vendor startup figures are not end-to-end FaultLine measurements |
| S36 | [Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) | Aggregate resource organization and control; host delegation must be available |
| S37 | [SQLite WAL](https://www.sqlite.org/wal.html) | Local concurrency and deployment constraints |
| S38 | [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html) | Row/advisory lock behavior; application transaction design remains necessary |
| S39 | [Temporal workflow execution](https://docs.temporal.io/workflow-execution) | Durable workflow concepts; execution isolation and external effects are separate |
| S40 | [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/) | Span/context correlation; not complete deterministic session replay |
| S41 | [OpenTelemetry sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/) | Context-dependent data minimization and handling responsibilities |
| S42 | [Google SRE: handling overload](https://sre.google/sre-book/handling-overload/) | Admission and overload-management principles |
| S43 | [Google SRE: canarying releases](https://sre.google/workbook/canarying-releases/) | Partial release evaluation; does not justify a universal traffic policy |
| S44 | [SLSA v1.2](https://slsa.dev/spec/v1.2/) | Supply-chain levels, tracks, and provenance formats; not a compliance certificate |
| S45 | [in-toto](https://in-toto.io/) | Supply-chain step integrity framework |
| S46 | [Sigstore blob signing](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/) | Artifact signing workflow; verifier issuer policy is essential |

### 24.6 Research limitations and unresolved references

- The main Sentry product guide returned an unsupported-content response; the readable official API documentation and changelog were used for the narrow competitive observations.
- The Code Shield GitHub source page was not successfully retrieved. Current tool coverage and packaging were not verified.
- Initial guessed accessibility and Pact deep links failed; the readable official accessibility guide and Pact documentation index are cited above.
- A SWE-bench evaluation deep link was unavailable in this pass; the original paper and official benchmark site support the limited evaluation discussion.
- This research did not authenticate to provider dashboards, inspect personal credits, submit jobs to paid model APIs, contact users, publish materials, or execute experiments proposed in this notebook.
- Broader legal, compliance, licensing, and security conclusions are outside this source review. Those questions should be investigated when a concrete deployment or distribution decision requires them.
