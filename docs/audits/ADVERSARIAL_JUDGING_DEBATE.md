# Adversarial judging debate

Date: November 3, 2026. Assessed revision: `82c0b8e`. Rubric: [`meta_rubric.md`](../../.agents/skills/hackathon-judge/references/meta_rubric.md); question bank: [`adversarial_grill.md`](../../.agents/skills/hackathon-judge/references/adversarial_grill.md).

This is a skeptical internal review, not an official Meta judging result or a placement prediction. A contrarian judge raised each objection below. A response survives only if code, a test run, or a committed evidence record supports it. Each exchange is marked **held**, **shaky**, or **failed**, following the skill's Phase 3 convention. When documentation and code disagreed, the code won, and the disagreement is recorded as a finding.

**Bottom line: 72/100.** The verification engine and the Linux sandbox are real and heavily tested, and the Meta integration goes well beyond a bare API call. Points were withheld for four reasons:

- Impact is unmeasured.
- Meta's evidence covers one scenario.
- The macOS and Windows isolation adapters are not functional yet.
- The narrated video does not exist.

Three status claims in the repository overstated the evidence. They are listed in [Documentation corrections](#documentation-corrections) and were fixed in the same change.

## Verification run for this review

All four commands below were run on `82c0b8e` in a clean worktree, after `npm ci` against the committed lockfiles.

| Command | Result |
| --- | --- |
| `make check` | **Exit 0.** Backend/root: **328 passed, 23 skipped** (native Windows coverage). Orchestrator/CLI: **1,238 passed**. Browser-runner unit: **134 passed**. Ruff lint and format, strict mypy, fixture and corpus provenance, all three Next.js/TypeScript builds, and both Python distributions passed. |
| `make browser` | **Exit 0.** Inspector: **52 passed** (48.6 s). Storefront: **2 passed**. |
| Total | **1,700 automated + 54 browser = 1,754 tests passing.** |
| `make integration` | **Not run.** Its lifecycle tests share cgroup scope names with any concurrent run in another worktree, and the [2026-11-03 record](../evidence/2026-11-03-backend-security-hardening.json) shows overlap causing spurious failures. The latest recorded run is 51 passed, 0 skipped (`FAULTLINE_REQUIRE_ISOLATED_TESTS=1`) at `433e87f`. |
| Targeted P04/P06/P07 unit tests | 25 passed (all mocked, no Bubblewrap needed). |

The first `make check` attempt exited 2 with `eslint: command not found`, because the fresh worktree had no `node_modules`. That is the same setup gap the [backend perfection check](BACKEND_PERFECTION_CHECK.md) recorded. It is not a code defect, but `make setup` must run first.

---

## 1. Impact (30%)

### Objection 1.1: "Silent checkout breakage is a $100M+ problem. Prove FaultLine stops revenue leaks."

**Contrarian:** You're pitching revenue protection. Show me the dollars.

**Evidence:** No dollar, market-size, or cart-abandonment figure appears anywhere in `docs/`, and none should. `README.md` states: "There are no measured customer adoption figures, revenue recovered, recovery SLA, or external judging score." In [`IMPACT_EVIDENCE.md`](../IMPACT_EVIDENCE.md), the intended-user feedback table is empty and the time-baseline row reads "Not yet supplied." The grill's own boundary applies: "No measured customer savings exist yet. Use labeled assumptions for estimates, never realized revenue."

What *is* measured is the mechanism by which revenue leaks hide. On the [hash-pinned adversarial corpus](../EVALUATION.md#what-verification-catches), six plausible wrong repairs were authored for the seeded defect:

- A "does checkout now return 201" symptom check accepted **5 of 6**.
- FaultLine's 27 business checks accepted **none**, and accepted both correct repairs.

One accepted wrong patch returns 201 while silently dropping the order. The corpus hashes are enforced by `make provenance` (`fixtures/evaluation/corpus.py`).

**Verdict: shaky.** The "$100M+" framing must not be spoken. The defensible claim is narrower: on an authored corpus, a status check misses five of six revenue-affecting wrong fixes, and FaultLine catches all six.

### Objection 1.2: "Did this happen to you, or is it a story built backwards from the demo?"

**Evidence:** [`IMPACT_EVIDENCE.md#firsthand-relevance`](../IMPACT_EVIDENCE.md#firsthand-relevance) records the builder's account:

- A hotfix silenced intermittent coupon-path 500s.
- The same hotfix short-circuited coupon normalization and tax.
- The margin loss went undetected for nearly five hours, until reconciliation flagged it.

**Verdict: shaky.** The account is firsthand by attribution but carries no company, date, amount, or log, and it closely mirrors the seeded defect. A judge will notice the resemblance. Its final sentence ("routinely convert visible server errors into invisible, catastrophic business logic regressions") generalizes beyond one incident.

### Objection 1.3: "Is this production monitoring?"

**Evidence:** No. `README.md` says "There is no continuous production monitoring." FaultLine runs bounded, on-request jobs against **one registered live defect**. The unfamiliar-defect corpus (nine variants) is measured offline.

**Verdict: held.** The docs are honest about this. The voiceover's "autonomous immune system for web applications" contradicts them and was corrected (see below).

**Impact score: 18/30 (Moderate).** The problem is specific, and the wrong-fix corpus is a genuinely sharp result. But there are no users, no measured savings, one route, and one uncorroborated anecdote.

---

## 2. Creative use of Meta AI tooling (25%)

### Objection 2.1: "Why Meta? Is muse-spark-1.3 doing the work, or is this a deterministic script with a Meta logo?"

**Evidence:**

- **Default model.** It is `muse-spark-1.3` (`model_adapter.py:43`), against `https://api.meta.ai/v1`.
- **Provider identity.** It comes from the endpoint host, never from configuration labels (`META_HOST_SUFFIXES = ("meta.ai", "meta.com", "llama.com")`, `model_adapter.py:34`).
- **Live trials.** On October 31, 2026, three live trials **all verified on the first attempt at 44/44 assertions**, with a median wall time of 10.5 s ([ledger](../evidence/2026-10-31-controller-ledger-meta.md)). `scripts/trial_ledger.py --require-provider meta` refuses to record a non-Meta response.
- **Retained replays.** Two Meta jobs are published as checksummed static replays: `3573b32b` (one attempt) and `82ac2dcc` (one retry).
- **Fallback separation.** The deterministic fallback runs only when no API key is configured (`model_adapter.py:488`). It is labeled `deterministic-checkout-v1` and is never counted as Meta. `test_provider_errors_never_fall_back` (`test_model_adapter.py:169`) proves that a configured Meta failure does not silently switch providers.

**Verdict: held** for "Meta generates the patch." **Shaky** for "why Meta specifically": no comparison against another provider was run *with Meta* on the same corpus. Meta has **not** been run on the nine-variant unfamiliar-defect corpus. Only DeepSeek (18/20) and the fallback (1/10) have.

### Objection 2.2: "You claim Llama 3.3 70B. Where's the run?"

**Evidence:** There is none. `Llama-3.3-70B-Instruct` appears only in `services/repair-orchestrator/README.md:34` and `docs/index.html`, which honestly says "No recorded run yet." In code, the only Llama references are the `llama.com` host suffix and one host-classification test. No test or trial uses that model ID. Because `reasoning_effort` defaults to `"low"` and non-reasoning models reject the field, a Llama run would likely also need `META_REASONING_EFFORT=none`.

**Verdict: failed** as a performance claim, **held** as a configuration claim. Say "configurable via `META_MODEL_NAME`, not yet trialed."

### Objection 2.3: "Why is ~3,200-token prompt containment better than dumping the whole repo into context?"

**Evidence:** The figure needs correcting first. Across the three ledger trials, mean **total** usage is about 3,240 tokens:

| Trial | Prompt | Completion | Total |
| ---: | ---: | ---: | ---: |
| 1 | 1,580 | 1,303 | 2,883 |
| 2 | 1,580 | 1,856 | 3,436 |
| 3 | 1,573 | 1,825 | 3,398 |

The **prompt** is about 1,578 tokens. "~3,200" is prompt plus completion, not the containment window.

The prompt holds the target file, the failure evidence, and the checkout's business contract. It never names the defect or its fix; `test_model_adapter.py:80-87` asserts that `"optional-coupon"` and `"get(coupon_code, 0)"` do not appear. Its inputs are capped:

- source at 32 KiB (`policy.py:17`)
- untrusted evidence at 16 KiB (`model_adapter.py:27`)
- the whole wire request and response at 64 KiB (`:28`)
- retry feedback at 4 KiB of diff, 12 checks, and 240 bytes per field (`:29-31`)

Evidence is JSON-encoded under an `UNTRUSTED_EVIDENCE` label with an explicit "no authority" instruction (`:272`, `:284`).

There is **no measured full-repo baseline**. No code, ledger, or evidence compares context sizes, and `LONG_TERM_RESEARCH_AND_IDEAS.md` lists that as future work. The defensible advantages are architectural, not empirical:

- Less untrusted text reaches the model, which shrinks the injection surface.
- No repository content leaves the machine beyond one file.
- Cost and latency are bounded by a hard wire cap.

The grill boundary also holds: containment "establishes instruction/data boundaries; deterministic gates and containment remain necessary."

**Verdict: shaky.** Do not say "superior." Say "bounded by design to one file plus 16 KiB of evidence; we have not benchmarked it against full-repo context."

### Objection 2.4: "Verifier-guided repair sounds like a retry loop with extra steps."

**Evidence:**

- **Strict proposal contract.** Proposals must satisfy a five-field schema (`shared/contracts/models.py:324-331`, `extra="forbid", strict=True`), sent as a strict `json_schema` response format.
- **Strict decoding.** `_decode` (`model_adapter.py:418`) rejects:
  - a mismatched model ID
  - anything other than exactly one choice
  - a non-`stop` finish reason
  - refusals and tool calls
  - schema violations
- **Feedback on rejection.** If attempt 1 is rejected, attempt 2 receives the exact evidence: a policy error and the rejected diff, or `FailedCheck(id, expected, observed)` tuples from verification (`worker.py:677-682`, `:747-755`).
- **No invented feedback.** Transport failures pass none (`test_worker_lifecycle.py:272`).
- **Attempt cap.** At most two attempts (`worker.py:578`), and the second is skipped if the deadline is short.
- **Hunk recount.** Miscounted hunk headers are recounted without touching content lines (`policy.py:199-251`), and the original diff is retained.

**Verdict: held** for the mechanism, which has tests. **Shaky** for Meta evidence: the only recorded Meta retry (`82ac2dcc`) was a *tooling* rejection (`git apply` refused a zero-context hunk, since fixed in `a69d705`), not a behavioral check failure. No "Meta fails a business check, gets the findings, and fixes it" run exists.

**Meta AI tooling score: 19/25 (Strong).** The rubric's Pinnacle band mentions structured repair contracts, prompt containment, and validation feedback, and all three exist in code. Meta's live evidence, though, is 3 of 3 runs on one scenario. It has no corpus run, no behavioral retry, and no Llama run.

---

## 3. Technical depth (20%)

### Objection 3.1: "A Git worktree isn't a sandbox. What actually stops candidate code from breaking out?"

**Evidence (Linux, `isolated_runtime.py`):**

- **Bubblewrap flags.** The launch uses:
  - `--unshare-all` plus `--unshare-user` (`:664`)
  - `--die-with-parent` (`:667`)
  - `--new-session` and `--clearenv`
  - `--cap-drop ALL` (`:670`)
- **Mounts.** `/usr`, `/lib`, the interpreter, packages, and the snapshot are bound read-only. `/tmp` is a 16 MiB tmpfs. `/`, `/dev`, and `/proc` are remounted read-only.
- **No network.** The network namespace is unshared, and the backend serves only an inherited listener.
- **Aggregate cgroup limits.** A transient systemd user scope sets `MemoryMax=512 MiB`, `MemorySwapMax=0`, `TasksMax=64`, `CPUQuota=100%`, and `OOMPolicy=kill` (`:103-107`).
- **Kernel read-back.** `verify_scope` (`:787`) reads `memory.max`, `memory.swap.max`, `pids.max`, `cpu.max`, and `memory.oom.group` back from the kernel and requires an exact match. A value of `max` is rejected.
- **Readiness probe.** Before readiness, `_enforcement_probe` (`:891`) runs a 64 MiB / 16-task scope and requires a SIGKILL, `oom_kill>=1`, and `pids.events max>=1` from *that scope's own* counters.
- **Recorded runs.** Every backend session in both recorded evaluation runs logged verified limits (48 of 48 and 19 of 19).
- **Tests stay outside.** The trusted checks run outside the namespace, against the sandboxed build. The candidate cannot see or edit them.

**Verdict: held.** The stated limits are also honest: there is no seccomp filter, the kernel is shared, and the CPU quota is read back but never probed.

### Objection 3.2: "You claim native macOS sandbox-exec and Windows Job Object isolation. Show me it working."

**Evidence:** The adapters exist (`app/isolation/darwin.py`, `windows.py`), and their tests pass on Linux. Those tests check generated argv, profile text, and hardcoded limits under monkeypatched `sys.platform`. Neither adapter has been exercised natively, and inspection found blocking defects:

- **macOS: the preflight can never pass.** `_profile_preflight` (`darwin.py:248-259`) builds a `python -c` program that places `try:` after semicolon-joined statements on one line. Compiling it raises `SyntaxError`, confirmed for this review. The adapter therefore always fails closed with `isolated_profile_unavailable`. That failure is safe, but the adapter is not functional.
- **macOS: the limits are self-certified.** The limit probe runs Python without the launcher, so no rlimits apply. In Docker mode, `verify_scope` returns the configured values with `verified=True` and reads nothing back (`darwin.py:211-218`).
- **Windows: the limits are self-certified.** Job Objects are created through C# P/Invoke in PowerShell. But `verify_scope` hardcodes `verified=True` without `QueryInformationJobObject` (`windows.py:274-281`), and the process is assigned to the job *after* it starts (`:177-178`), which leaves a window.
- **Windows: no filesystem or network isolation.** Neither exists.
- **Sandbox repair: Linux only.** `cli_check.py` states "Sandbox repair requires Linux with systemd and cgroup v2." The macOS/Windows CI job (`platform-smoke.yml`) smoke-tests the gate CLI, not isolation. [`MULTIPLATFORM_ISOLATION.md`](../MULTIPLATFORM_ISOLATION.md) itself says those paths "must be exercised on their own hosts."

**Verdict: failed** as stated. The accurate claims are:

- The **pre-flight gate CLI** runs natively on macOS, Linux, and Windows (CI-tested).
- **Contained sandbox repair** is Linux-only.
- macOS and Windows isolation adapters are scaffolded and fail closed, but are not validated.

### Objection 3.3: "Your own audit found eight backend isolation bugs. Are P01–P07 really fixed?"

**Evidence:** Not all of them, and not all with probes. Every verdict below comes from comparing the [audit](BACKEND_PERFECTION_CHECK.md) and its probes to the current source.

| ID | Finding | Status at `82c0b8e` | Proof |
| --- | --- | --- | --- |
| P01 | Chromium fallback leaks WebRTC UDP | **Fixed** | Executable probe re-run: 0 UDP bytes on both real launch paths ([record](../evidence/2026-11-03-backend-security-hardening.json)) |
| P02 | DB write fault skips cleanup | **Fixed** | Fault-injection probe re-run plus regression tests (same record) |
| P03 | Late cancellation escapes cleanup | **Fixed** | Cancellation probe re-run plus regression tests (same record) |
| P04 | Stop timeout skips cgroup release | **Fixed in `26b032e`** | Regression tests only (`test_backend_stop_failure_releases_scope_and_local_handles`, generation/project cleanup tests), mocked; no probe re-run recorded |
| P05 | Catch-all policy binding gaps | **Fixed** | AST probe re-run plus policy tests (same record) |
| P06 | Host browser/artifact work unbounded | **Partially fixed in `26b032e`** | The project-mode browser has its own scope (1 GiB / 256 tasks), a 64 MiB tmpfs, `RLIMIT_FSIZE`, and bounded artifact streaming. The fixture path's Next.js frontend and Playwright runner still run unscoped on the host (`isolated_runtime.py:1065-1075`, `:1422-1436`) |
| P07 | Snapshot identity misses extra files | **Fixed in `26b032e`** | `_verify_snapshot` whole-root allowlist (`:1265`), tested by `test_snapshot_rejects_unhashed_mount_entries`; the verify-then-mount race remains |
| P08 | CI does not require live containment paths | **Open** | Makefile and workflows unchanged; `make integration` omits the project/repro files and CI never sets `FAULTLINE_REQUIRE_ISOLATED_TESTS` |

The audit's edge probe (`docs/audits/probes/backend_perfection_edges.py`) **now crashes** with `CandidateRejected: snapshot_nonapplication_file`. That error is indirect evidence that P07's fix works, but the script exits before reaching the P04 stop probe, so it cannot currently serve as executable proof for P04, P06, or P07.

**Verdict: failed** for "P01–P07 resolved by executable probes." The defensible statement is: **"P01, P02, P03, and P05 are fixed and confirmed by re-running the audit's probes; P04 and P07 are fixed with regression tests; P06 is partly fixed; P08 is open."**

### Objection 3.4: "Is 1,754 tests a real number, or padded?"

**Evidence:** The count was reproduced above on this revision. It does not double-count: isolated-runtime tests sit inside the 1,238 orchestrator count, and the 23 Windows skips are excluded. The suite is fast (orchestrator 81 s) and fails closed: `FAULTLINE_REQUIRE_ISOLATED_TESTS=1` turns unavailable prerequisites into failures.

**Verdict: held.** Count is not coverage, though. The macOS/Windows adapter tests demonstrate that a high count can coexist with a non-functional path.

**Technical depth score: 17/20 (Strong).** The Linux containment is genuinely Pinnacle-grade: kernel read-back plus adversarial probes. The score is held back by:

- no seccomp filter
- partial P06 and open P08
- self-certified limits on non-Linux adapters
- a broken audit probe

---

## 4. Demo and presentation (25%)

### Objection 4.1: "Is the 3-minute pitch reproducible?"

**Evidence:** The [storyboard](../VIDEO_STORYBOARD.md) ends at exactly 3:00. The [voiceover](../VOICEOVER_SCRIPT.md) has two cuts, Track A at 133.8 s and Track B at 159.5 s, both under the limit.

The rough cuts are gitignored local builds (`scripts/assemble-footage.sh`, `assemble-extended-cut.sh`). They currently have **no audio stream**. The Devpost video link is still "TODO (owner)."

The storyboard and the voiceover also diverge. The storyboard includes a live Apply/Revert cue and a limits cue; the voiceover tracks include neither.

**Verdict: shaky.** The scripts are reproducible, but the deliverable does not exist yet. This is the single largest remaining risk to the score.

### Objection 4.2: "What happens when the Wi-Fi dies or the Meta key fails on stage?"

**Evidence:** Three layers exist, and each one is labeled:

1. **Deterministic provider.** Without `META_API_KEY`, the stack runs on `deterministic-checkout-v1`, labeled in the Inspector as "Deterministic fallback · … · no model call" (`faultline-api.ts:385,394`). The repair button reads "Auto-repair (deterministic-checkout-v1)," not "Repair with Meta." `rehearse-demo.sh` prints "Deterministic rehearsal: this is not a live Meta trial."
2. **Static replays.** Three checksummed replays on GitHub Pages need no backend: Meta `3573b32b`, Meta-with-retry `82ac2dcc`, and deterministic `83d1c403`. All of their `SHA256SUMS` verify.
3. **Local-only stack.** All demo services bind to `127.0.0.1`. `demo-chaos.sh` needs only `uv` and `jq`.

`start-demo.sh` runs `uv sync --locked` and three npm builds on every start. That should work offline with warm caches, but this was not tested. Pre-warm before stage.

**Verdict: held.** The fallback cannot be mistaken for Meta.

### Objection 4.3: "Does the narration overclaim?"

**Evidence:** It did, in four places:

- "an autonomous immune system for web applications" (there is no continuous monitoring)
- "real customer transactions are dead" (only coupon-less checkouts fail)
- "All footage was recorded live" (the Meta segment is a retained replay, as its own caption says)
- "thirty interactive elements," which has no row in the claim-sources table

**Verdict: failed → corrected.** The first three were rewritten at similar spoken length. The fourth is flagged in the script's claim table for the owner to confirm against the recorded gate output.

**Demo score: 18/25 (Strong, low end).** The flow is complete, honestly labeled, and survives an offline failure. The narrated video is missing, and the storyboard and narration need reconciling.

---

## Final scoring

| Criterion | Weight | Awarded | Band | Main deduction |
| --- | ---: | ---: | --- | --- |
| Impact | 30 | **18** | Moderate | No users, no measured savings, one route, uncorroborated anecdote |
| Meta AI tooling | 25 | **19** | Strong | 3/3 trials on one scenario; no Meta corpus run, behavioral retry, or Llama run |
| Technical depth | 20 | **17** | Strong | No seccomp; P06 partial, P08 open; non-Linux adapters non-functional |
| Demo & presentation | 25 | **18** | Strong | Narrated video not recorded; storyboard and voiceover diverge |
| **Total** | **100** | **72** | | |

For comparison, the October 27 [internal assessment](HACKATHON_SCORE_ASSESSMENT.md) scored **55/100**. Most of the gain comes from live Meta trials and replays (+11 tooling) and a firsthand account plus the wrong-fix corpus (+4 impact).

## Highest-value remediation before submission

Ranked by points recoverable per hour:

1. **Record and mux the voiceover** onto the rough cut, then link it on Devpost. Demo: up to +4.
2. **Run Meta on the unfamiliar-defect corpus** (`make evaluate` with `META_API_KEY`). Even 2 trials × 10 cases would answer objection 2.1. Tooling: up to +3.
3. **Fix `backend_perfection_edges.py`** to treat the P07 rejection as a pass and continue to the P04 stop probe. Commit the output as an evidence record. Technical: +1.
4. **Fix or withdraw the macOS adapter preflight.** The `SyntaxError` is a one-line fix, but only a native macOS run can validate it. Until then, keep "Linux-only sandbox repair" in all copy.
5. **Collect even two real user conversations** for `IMPACT_EVIDENCE.md`. Impact: up to +3.

## Documentation corrections

These were made in the same change as this report:

- [`DEVPOST_SUBMISSION.md`](../DEVPOST_SUBMISSION.md) gained these additions:
  - the verified 1,754-test count with its breakdown
  - the P01–P08 status as stated in objection 3.3
  - an accurate cross-platform statement: the gate is native on three operating systems, and sandbox repair is Linux-only with macOS/Windows adapters not yet validated

  It also lost one overclaim: "sandboxed execution … essential" for correctness.
- [`VOICEOVER_SCRIPT.md`](../VOICEOVER_SCRIPT.md) changed as follows:
  - the test count was added to the sandbox segment's narration and to the claim-sources table
  - the three overclaims in objection 4.3 were rewritten
  - the "thirty interactive elements" claim was flagged for the owner to source
- [`PROJECT_STATUS.md`](../PROJECT_STATUS.md) changed as follows:
  - the P01–P07 line was replaced with the accurate per-finding status
  - "~3,200 tokens" is now identified as prompt plus completion (~1,580 prompt)
- [`BACKEND_PERFECTION_CHECK.md`](BACKEND_PERFECTION_CHECK.md) has a second follow-up note recording the `26b032e` fixes and that they lack probe evidence.
