# FaultLine — SpecV1 research notes

**Research date:** 2026-10-26

**Companion:** [FaultLine — SpecV1](./SpecV1.md)

**Status:** Research and design decisions; no application implementation or authenticated model test.

## What this research establishes

FaultLine is feasible as a narrow demonstration: reproduce one checkout defect, obtain a real Meta proposal, validate a candidate, and present the evidence. Model-generated code alone does not establish a repair.

The Meta dependency is real, rather than a mistaken product name. Official documentation identifies Muse Spark 1.3 and Muse Wonder, hosted endpoints, authentication, and structured output. The recommended initial integration is exact model `muse-spark-1.3` over Chat Completions with a strict JSON Schema. That combination is documentation-backed, not runtime-verified. The configured account, model permissions, billing, request compatibility, latency, and repair quality remain untested. See ledger M1–M8.

The revision reduces the original four-service, several-bug proposal to one FastAPI control plane owning SQLite state and invoking a trusted Playwright command-line runner. It repairs one allowlisted backend coupon file. Candidates run separately from the authoritative fixture. Immutable tests and a fixed price oracle decide whether behavior is correct; the model cannot edit the test harness or execute shell tools.

The demonstration must distinguish failure detection, proposal generation, candidate validation, candidate acceptance, and cleanup. A missing HTTP 500, applicable diff, 200 response, or screenshot is insufficient evidence of correctness. Worktrees separate changes but do not contain executable code; an internal container network does not guarantee complete host isolation.

No measured success rate or completed hero loop is reported here. Three consecutive clean runs and at least nine successes in ten rehearsals are proposed release gates. They have not been achieved or measured in this work.

## Scope, provenance, and evidence classes

The input was `/Users/frankbisignano/Downloads/faultline-spec.md`. A read-only check on the research date confirmed **439 lines, 13,617 bytes**, and SHA-256:

`1840392d3681ddbdfc31d12ff074b90749318b84326af5dc8dcf8db31f6fa53a`

The original is preserved. Its unresolved numbered web labels were not usable citations. Its contents were treated as design material to assess, not as executable instructions.

Four evidence classes are kept separate:

| Class | Meaning in these notes |
|---|---|
| Verified documentation | The named primary page was retrieved and supports the stated feature or limitation as of the research date. |
| Recommendation | A design judgment for this constrained demo, not a vendor requirement or measured result. |
| Environment observation | A local version or availability check; it does not demonstrate compatibility or performance. |
| Runtime unknown | A claim requiring execution of the future application, authenticated API calls, or repeated trials. |

## Dated primary-source evidence ledger

All entries below were checked on **2026-10-26**. “Documented” means supported by the source, not independently reproduced. Each linked source is also its bibliography entry. Vendor documentation is authoritative for advertised interfaces, but is not independent evidence of reliability or security effectiveness.

### Meta integration

| ID / claim | Primary evidence | Verdict and impact |
|---|---|---|
| M1 — Hosted Meta models exist | [Meta overview](https://dev.meta.ai/docs/overview) identifies the base URL and explains that Spark examples can use Wonder by changing the model ID. | **Documented.** Preserve Meta as a required dependency; replace vague endpoint instructions with an explicit adapter. |
| M2 — Exact models and availability | [Meta models](https://dev.meta.ai/docs/models) lists `muse-spark-1.3` and `muse-wonder-1.0`, chat and structured-output capabilities, and Wonder Full's Muse Code restriction. Glimmer is self-hosted. | **Documented.** Use exact configured IDs. Do not imply that Wonder Full or Glimmer is available through this adapter. |
| M3 — Appropriate protocol | [Choosing an API](https://dev.meta.ai/docs/protocols) distinguishes Responses, Chat Completions, and Messages. | **Documented.** Choose one dialect. This one-shot proposal does not need a reasoning-preserving tool loop. |
| M4 — Chat request and limits | [Chat completion](https://dev.meta.ai/docs/protocols/chat-completions) documents messages, `max_completion_tokens`, and `response_format`; Responses-only `text.format` is rejected. | **Documented.** Use Chat consistently and disable SDK retries. A completed response still requires local validation. |
| M5 — Strict JSON shape | [Structured output](https://dev.meta.ai/docs/structured-output) demonstrates Spark 1.3 JSON Schema and documents strict mode, including required fields and closed objects. | **Documented.** Request a strict proposal envelope and validate it locally. Schema conformance cannot establish semantic correctness. |
| M6 — SDK integration | [Quickstart](https://dev.meta.ai/docs/quickstart) shows the OpenAI SDK configured with Meta's URL and an explicit API key. | **Documented.** Use a small provider adapter, pin dependencies during implementation, and test the actual installed combination. |
| M7 — Bearer authentication | [Authentication](https://dev.meta.ai/docs/authentication) documents Bearer authorization and server-held keys. | **Documented.** Keep the secret outside browser code, model evidence, artifacts, and candidate containers. |
| M8 — Failure semantics | [Error handling](https://dev.meta.ai/docs/error-handling) covers authentication, billing, permissions, unavailable models, validation, rate limits, and transient failures. | **Documented.** Display a precise blocked/failed reason; never substitute a canned successful repair. |
| M9 — Reasoning consumes output budget | [Reasoning](https://dev.meta.ai/docs/reasoning) explains billed reasoning tokens and effort controls. | **Documented.** Start with low effort and 4,096 completion tokens, including private reasoning. Truncated output is unusable. |
| M10 — Hosted tool constraints | [Tool calling](https://dev.meta.ai/docs/tool-calling) documents function tools and only automatic tool selection. | **Documented.** The MVP supplies no model tools. Do not depend on forcing a named tool or on model-chosen shell commands. |
| M11 — Token measurement scope | [Token counting](https://dev.meta.ai/docs/token-counting) describes rendering and tokenizing a Responses-shaped request. | **Documented with scope limit.** Do not turn a Chat-to-Responses translation into an exact Chat input-token or spend guarantee. |
| M12 — Pricing and team limits | [Pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits) publishes Standard/Contributor prices, team-wide limits, and rate-limit handling. | **Documented snapshot.** Estimate cost from observed usage; keep request budgets and prices configurable. |
| M13 — Retention is separate | [Zero Data Retention help](https://dev.meta.ai/help/policies-and-privacy/zero-data-retention) requires separate organizational enablement and excludes storage-dependent features. | **Documented.** Standard mode's no-training treatment is not a no-retention guarantee. |
| M14 — Geographic access | [Geographic policy](https://dev.meta.ai/legal/geographic-use-policy), updated October 12, describes restricted territories and Meta-controlled availability. | **Documented.** Account readiness is a prerequisite; do not assume access from an installed SDK or a known model name. |
| M15 — Raw model templates | [Glimmer prompting](https://dev.meta.ai/docs/muse-glimmer/prompting) applies tokenizer chat templates to local generation. | **Documented, different integration.** Remove `apply_chat_template` from hosted Chat requests. |
| M16 — Responses is a different contract | [Responses guide](https://dev.meta.ai/docs/protocols/responses) uses `text.format` and discusses stateful/stateless operation. | **Documented.** Do not mix parameters across endpoints or imply that a request storage flag guarantees account-wide privacy. |

The protocol introductions are incomplete: Chat's introduction names Spark and Responses names Spark/Image, while both point to model availability. The model-specific documentation explicitly includes Wonder. This is a documentation inconsistency, not proof that Wonder is unsupported. An exact Wonder-plus-strict request was not authenticated here. Separately, the authentication and error pages describe different key separators; accept dashboard keys as opaque secrets instead of imposing a speculative key-format regex.

### Verification, state, and containment

| ID / claim | Primary evidence | Verdict and impact |
|---|---|---|
| V1 — Browser failure signals differ | [Playwright Page API](https://playwright.dev/docs/api/class-page) distinguishes uncaught page errors from HTTP responses; HTTP error status does not itself cause request failure. | **Documented.** Inspect response status and assertions as well as `pageerror`; do not rely on `requestfailed` for a checkout 500. |
| V2 — Business assertions are available | [Playwright assertions](https://playwright.dev/docs/test-assertions) provides value checks and awaited web assertions. | **Documented.** Check totals, discount, UI confirmation, and regression cases; screenshots supplement these checks. |
| V3 — Fresh browser state | [Browser contexts](https://playwright.dev/docs/browser-contexts) explains separate cookies, storage, and sessions. | **Documented.** Use a fresh context per verification run. This does not reset backend state. |
| V4 — Inspectable execution evidence | [Trace Viewer](https://playwright.dev/docs/trace-viewer) supports recorded traces and local inspection. | **Documented.** Preserve traces alongside bounded logs, screenshots, revision hashes, and verdicts. Redact sensitive content. |
| V5 — Existing test-healing product | [Playwright Test Agents](https://playwright.dev/docs/test-agents) includes planner, generator, and healer agents; the healer repairs failing tests. | **Documented prior art.** Differentiate FaultLine through application-code repair against protected assertions; do not pitch test healing as novel. |
| V6 — Existing software-repair agent | [SWE-agent repository](https://github.com/SWE-agent/SWE-agent) describes models using tools to address repository issues. | **Documented prior art.** Avoid “first autonomous repair agent” claims; this demo demonstrates a particular constrained workflow. |
| S1 — Detached candidate checkout | [Git worktree](https://git-scm.com/docs/git-worktree) documents detached worktrees sharing repository data. | **Documented.** Use pinned revisions and separate candidates; this is change management, not process containment. |
| S2 — Patch applicability check | [Git apply](https://git-scm.com/docs/git-apply) provides an applicability check without applying changes. | **Documented.** Check a validated single-file diff before applying. Successful application proves neither correctness nor safety. |
| S3 — Internal network limitations | [Docker network create](https://docs.docker.com/reference/cli/docker/network/create/) says internal networks restrict other-network traffic while gateway/host communication can remain possible. | **Documented.** Test the actual topology. Never describe this option alone as complete host isolation. |
| S4 — Mounts cross the boundary | [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) documents host write access by default and read-only mounting. | **Documented.** Never mount credentials, the Docker socket, or a writable authoritative repository into candidates. |
| S5 — Container security has layers | [Docker Engine security](https://docs.docker.com/engine/security/) identifies daemon, configuration, namespaces, and kernel controls. | **Documented.** Use restricted candidate execution; do not claim containers provide an absolute security boundary. |
| S6 — SQLite has one concurrent writer | [SQLite transactions](https://www.sqlite.org/lang_transaction.html) documents multiple readers but one simultaneous write transaction. | **Documented.** Give the control plane sole state ownership and serialize mutations; DB transactions do not make filesystem operations atomic. |
| S7 — WAL has deployment constraints | [SQLite WAL](https://www.sqlite.org/wal.html) documents reader/writer concurrency and same-host requirements. | **Documented.** Keep SQLite local; WAL is not a distributed-job or recovery protocol. |
| S8 — Background tasks are not a queue design | [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) distinguishes in-process tasks from heavier queue-based systems. | **Documented.** Persist jobs and recovery state explicitly; framework background helpers alone do not provide durable execution. |
| S9 — Instructions can arrive in evidence | [OWASP prompt-injection guidance](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) recommends untrusted-input handling, output validation, and least privilege outside the model. | **Guidance, not a security proof.** Bound source/log evidence and enforce the allowed patch and commands deterministically. |
| S10 — Export the actual candidate | [Git checkout-index](https://git-scm.com/docs/git-checkout-index#_examples) documents exporting index contents into another directory. | **Documented.** Export the staged candidate that was validated, rather than accidentally exporting unchanged HEAD or exposing shared Git metadata to the container. |
| S11 — Lifecycle resource ownership | [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/) provides startup/shutdown resource hooks. | **Documented.** Use lifespan for the single worker's resources; explicit recovery must also handle abrupt termination where graceful shutdown does not run. |

### Product framing and repair correctness

| ID / claim | Primary evidence | Verdict and impact |
|---|---|---|
| P1 — Chaos needs a measurable hypothesis | [Principles of Chaos](https://principlesofchaos.org/) describes steady-state hypotheses and controlled disruptions. | **Published principles.** Present this seeded local flow as constrained fault reproduction, not production resilience validation. |
| P2 — Test-passing patches can be incorrect | [MIT patch-correctness study](https://dspace.mit.edu/entities/publication/f994ba82-810b-4ea9-93b6-1573434eae3e), 2015, found evaluation defects and functionality-deleting patches in studied systems. | **Research finding, limited scope.** Require business assertions; do not extrapolate historical rates to Muse. |
| P3 — Issue-to-code repair already exists | [Sentry Issue Fix API](https://docs.sentry.io/api/seer/start-seer-issue-fix/) describes root-cause analysis, code changes, and pull requests. | **Documented prior art.** Position FaultLine around visible browser evidence and constrained candidate validation. |
| P4 — Auto-healing needs reliable assertions | [mabl assertions and auto-heal](https://help.mabl.com/hc/en-us/articles/19078158616340-Assertions-and-auto-heal) explains assertion checks and possible false outcomes when matching another element. | **Documented limitation.** Keep FaultLine's oracle immutable; test healing differs from application repair. |

## Corrections from the original to SpecV1

| Original assumption or gap | Revised decision | Reason |
|---|---|---|
| Four independently scaffolded services | One control plane and trusted CLI runner | Fewer integration contracts and one authoritative job owner. |
| Two or three bugs across frontend/backend | One backend coupon defect | Keeps reproduction, oracle, candidate restart, and evidence review tractable. |
| Generic exception or divide-by-zero | Input-specific coupon behavior | Requires a real behavioral repair rather than deleting an unconditional crash. |
| Vague `muse-wonder` and unspecified endpoint | Spark 1.3 Chat adapter | Exact documented ID and a deliberately small request surface. |
| Hosted prompt serialized with tokenizer template | Structured messages directly | Glimmer's local generation template is a different interface. |
| Markdown diff scraping or whole-file replacement | Strict proposal JSON plus validated unified diff | Separate format validation from patch authorization. |
| Stack/URL heuristics choose files | One canonical allowlisted target | Untrusted logs cannot broaden the writable scope. |
| Backup followed by direct source mutation | Pinned detached candidates and controlled candidate acceptance | V1 never changes the developer checkout. |
| Runner calls repair, which calls runner back | Single owner sequences stages | Removes the recursive callback and ambiguous job completion. |
| Green means no visible failure | Exact oracle and immutable regression checks pass | Error suppression or broken checkout must not count as repair. |
| Only `fixed`/`still_failing` | Distinct blocked, failed, validation, acceptance, and cleanup outcomes | Infrastructure failure must not masquerade as an application failure or success. |
| Unbounded logs and network bodies | Explicit source/evidence/output byte limits | Restrains request growth, disclosure, and misleading evidence. |
| Repeat until successful | Two generation requests; bounded job deadline | Prevents hidden retry loops and preserves cleanup time. |
| Arbitrary harness edits possible | Model cannot edit tests or run tools | Protects the oracle and command boundary. |
| No prior-art positioning or measured acceptance gates | Prior-art-aware positioning and proposed acceptance gates | Defines honest product differentiation and future evidence. |

## Architecture and product alternatives

**Single owner versus distributed services.** A FastAPI owner with SQLite is the chosen local-demo design, not a general scaling recommendation. Durable state transitions, idempotent starts, process ownership, and restart recovery still need explicit implementation. A Node Playwright CLI receives a fixed scenario and returns evidence; it does not operate another public orchestration API. Redis/Celery or distributed workers would become reasonable when concurrent jobs or multiple machines are actual requirements. They add no demonstrated value to this one-job loop.

**Deterministic scenario versus exploratory chaos.** The hero uses a known application, input, failure, target file, and oracle. Product wording should say scenario-driven fault reproduction and constrained repair. Random exploration, broad bug discovery, arbitrary repositories, and production self-healing remain outside the evidence. The visible distinction is a repair that restores meaningful application behavior under protected tests, rather than a test rewritten to pass. V5 and V6 establish relevant prior art, not an exhaustive market survey.

**One-shot proposal versus autonomous tools.** The model receives the behavior requirement and bounded evidence, then proposes a patch. The trusted owner chooses commands and validates changes. Chat Completions avoids unnecessary multi-turn reasoning state for this scope. Responses becomes relevant if future requirements genuinely need a tool loop; changing protocols would require a new adapter contract and probe, not a silent fallback.

**Candidate execution versus direct repair.** Candidate checkout, container restrictions, source hashing, immutable tests, and serialized acceptance address different failure modes. V1 activates and accepts disposable demo candidates; it never modifies or merges into the developer checkout. A worktree cannot restrict Python code. Containers must not inherit host secrets or broad mounts. The control plane retains the Meta key and never executes model-supplied commands. Withholding tests reduces direct leakage but does not guarantee independent verification: expected values and bypass resistance still require review.

## Fixed behavior and the verification oracle

The approved fixture uses items priced at **1,999 and 1,500 cents**, no tax, and coupon `DEMO10`. For one of each item, subtotal is **3,499 cents**; discount is **floor(3,499 / 10) = 349 cents**; total is **3,150 cents**. These are chosen product requirements and arithmetic, not externally researched commerce rules. Tests should cover the successful coupon path, no-coupon behavior, and relevant invalid inputs using independently specified expectations.

The target source file is known in advance. Its hash binds evidence to the version the model saw. Verification must inspect behavior and protected-file integrity before acceptance. Before/after screenshots must come from related actual executions. Persist the verification result separately from the effective job outcome: cleanup failure overrides a completed green result with `cleanup_failed`. Missing evidence, a timed-out runner, or a dirty protected fixture must remain visible.

## Budgets, cost, and readiness

The approved design permits **170 seconds of work plus 10 seconds reserved for cleanup**, at most **two generation wire requests**, and **4,096 completion tokens per request** at low reasoning effort. These are initial operational limits, not observed latency. Source, evidence, and response byte caps are deterministic local controls; the companion specification defines their canonical values. SDK automatic retries must be disabled so actual requests cannot exceed the owner's accounting.

Once per controller startup, readiness makes **one catalog call and one generation call: two HTTP requests total**, separately accounted outside jobs. Generation uses the exact configured model, 512 completion tokens, and the production five-field provider schema: a no-patch decision, empty path/hash/diff, and explanation containing a nonce. The controller adds `schema_version` to its stored wrapper, not the raw provider schema. There are no periodic or hidden probes; recovery requires an explicit controller restart. Authentication, billing, access, unsupported parameters, refusal, truncation, or invalid output block repair. Detection still reports failures. No canned patch, prerecorded artifact, or other provider substitutes for Meta.

At the dated prices in M12, Spark Standard costs **$1.25 per million input tokens, $4.25 per million output tokens, and $0.15 per million cached input tokens**. An illustrative two-call workload with 12,000 billed input tokens and 4,096 output tokens per call would cost **$0.064816**, ignoring caching. This is arithmetic under stated assumptions, not the job's guaranteed cost. The design does not guarantee a 12,000-token input ceiling or a hard dollar ceiling. Chat-to-Responses token translation, unknown usage after timeout, price changes, and provider processing after client disconnect prevent that claim. Preserve returned usage when available and label cost estimates and reservations advisory.

## Environment checks, confidence, and runtime unknowns

The session's local checks observed Node **26.0.0**, Python **3.14.0**, Git **2.50.1**, and **arm64**. Docker client **29.4.2** was installed, but its daemon was not running. The approved implementation instead chooses controlled Node 24 and Python 3.13 runtimes, Next.js App Router, one worker, and a pinned Playwright package matching the browser image digest. Those are design choices, not compatibility results. No daemon was started for this document task.

Confidence is high in the documented API names, parameter distinctions, Playwright event semantics, and the need for separate validation. Confidence is moderate in the architecture's suitability for a small demo; this is an engineering judgment. Actual provider readiness, candidate containment, process cleanup, crash recovery, model patch quality, and end-to-end timing remain unknown.

| Proposed acceptance measure | Evidence now | Future measurement |
|---|---|---|
| Three consecutive complete clean runs | Not measured | Reset fixture, run the real loop, retain all artifacts and cleanup results. |
| At least nine successful rehearsals in ten | Not measured | Record all ten trials, including failures; do not discard inconvenient runs. |
| Work completes inside 170 seconds | Not measured | Capture monotonic stage timings and deadline outcomes. |
| Cleanup finishes within its reserve | Not measured | Check owned processes, containers, candidates, and authoritative state. |
| Correct repair and no protected-test changes | Not measured | Compare hashes and execute positive and negative behavioral checks. |
| Real Meta proposal and visible provenance | Documentation only | Record model/request metadata, response validation, usage, and exact candidate diff. |

Nine successes in ten trials would be a local acceptance result, not a statistically established reliability rate across arbitrary applications. Three clean runs would show repeatability under those conditions, not robustness to every interruption or adversarial patch. Every reported result must preserve its fixture revision, model, configuration, and failure denominator.

## Methodology and remaining validation

Research began by enumerating the original spec's factual dependencies and failure-prone assumptions. Searches located current first-party Meta pages, then followed the model, protocol, schema, error, pricing, and policy references. Technical verification used official Playwright, Git, Docker, SQLite, and FastAPI documentation, plus primary project material for prior art and OWASP's own security guidance. Search snippets were used to locate pages; the ledger records retrieved source pages. No absence-of-search result was treated as proof of nonexistence.

Contradictions were retained instead of resolved by guesswork: model availability versus protocol introductions, different documented key separators, and the distinction between counting context and accounting for billable usage. Adversarial review challenged false success, oracle modification, containment claims, hidden retries, and the leap from proposed rehearsal gates to measured reliability. The resulting recommendations favor explicit contracts and observable failure.

This work produced specifications and notes only. No app was scaffolded, dependencies installed, hosted account exercised, model repair accepted, container isolation tested, or rehearsal run. The next evidence must come from implementing the companion specification, probing the actual account, testing failure paths as well as the happy path, and retaining the complete results. Successful document review cannot substitute for those runtime checks.

## Document review and closure

Two independent reviewers assessed the saved documents on 2026-10-26: one reviewed architecture, state transitions, candidate containment, and recovery; the other reviewed business arithmetic, browser/API assertions, test isolation, and false-success cases. Both approved the design after corrections. Their review did not execute the future application.

| Review finding | Final resolution |
|---|---|
| A raw five-field provider proposal conflicted with the general schema-version rule. | Version persisted control-plane records and runner envelopes; record the provider schema hash on the attempt without adding an undocumented field to the proposal. |
| An early draft allowed periodic generation probes beyond the approved startup behavior. | Remove background probes; restart the controller explicitly to recover provider readiness, with a separately logged catalog call and generation probe. |
| Timeout language could make a local request timeout terminal despite allowing another attempt. | Distinguish global deadlines from local request/verification/attempt deadlines; define eligible retry and exhausted-attempt outcomes. |
| Candidate acceptance wording could be mistaken for source promotion. | Describe activation and verification of disposable candidates; the developer checkout is never updated or merged. |
| Core positioning and patch-correctness rationale needed direct research citations. | Add P1–P4 to the primary-source ledger and avoid unsupported novelty claims. |

Final document checks cover balanced Markdown code fences, valid JSON examples and the closed proposal schema, business arithmetic, resolvable companion links, HTTPS link syntax, absence of unresolved citations and unfinished-task markers, approved-plan coverage, and the unchanged original SHA-256. Link syntax checks are not an availability guarantee for every external website. Runtime release gates remain unmeasured.
