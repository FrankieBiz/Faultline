# Adversarial judging debate

Date: November 3, 2026. Assessed revision: `82c0b8e`. Rubric: [`meta_rubric.md`](../../.agents/skills/hackathon-judge/references/meta_rubric.md); question bank: [`adversarial_grill.md`](../../.agents/skills/hackathon-judge/references/adversarial_grill.md).

**Round 2 update:** [Round 2](#round-2) re-scored the project at **73/100** on `f143778`. It also records that hosted CI has been red since `7ec953f`, which Round 1 did not check.

This is a skeptical internal review, not an official Meta judging result or a placement prediction. A contrarian judge raised each objection below. A response survives only if code, a test run, or a committed evidence record supports it. Each exchange is marked **held**, **shaky**, or **failed**, following the skill's Phase 3 convention. When documentation and code disagreed, the code won, and the disagreement is recorded as a finding.

**Bottom line: 72/100.** The verification engine and the Linux sandbox are real and heavily tested, and the Meta integration goes well beyond a bare API call. Points were withheld for four reasons:

- Impact is unmeasured.
- Meta's evidence covers one scenario.
- The macOS and Windows isolation adapters have never run on their own hosts.
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
| After merging `ef54542` (adapter hardening, landed mid-review) | `make check` **exit 0**: 328 passed / 23 skipped, orchestrator **1,272 passed / 3 skipped** (Windows-only adapter tests), runner 134. `make browser` **exit 0**: 52 + 2. That is **1,734 automated + 54 browser = 1,788** on the merged head. The submission copy keeps the 1,754 figure pinned to `82c0b8e`, where it was measured. |

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

**Evidence at `82c0b8e`:** The adapters exist (`app/isolation/darwin.py`, `windows.py`), and their tests pass on Linux. Those tests check generated argv, profile text, and hardcoded limits under monkeypatched `sys.platform`. Neither adapter has been exercised natively, and inspection found blocking defects:

- **macOS: the preflight could never pass.** `_profile_preflight` built a `python -c` program that placed `try:` after semicolon-joined statements on one line. Compiling it raises `SyntaxError`, confirmed for this review. The adapter therefore always failed closed with `isolated_profile_unavailable`.
- **macOS: the limit probe tested nothing.** It ran Python without the launcher, so no rlimits applied. In Docker mode, `verify_scope` returns the configured values with `verified=True` and reads nothing back.
- **Windows: the limits were self-certified.** The process was assigned to its Job Object *after* starting, the assignment result was ignored, and no `QueryInformationJobObject` read-back existed.
- **Windows: no filesystem or network isolation.** Neither exists.

**Rebuttal landed during this review:** commit `ef54542` (merged on `main` while this report was being written) addresses most of the list above. Its own [adversarial review](../../services/repair-orchestrator/app/isolation/ADVERSARIAL_REVIEW.md) records the changes:

- **macOS preflight.** It now generates valid Python, and a regression test compiles it.
- **macOS memory probe.** It applies the launcher's real rlimits first and rejects a missing `MemoryError`.
- **macOS process control.** The profile denies `process-fork` and escapes profile strings.
- **Windows job assignment.** The candidate is created `CREATE_SUSPENDED`, assigned with a checked `AssignProcessToJobObject`, then resumed.
- **Windows read-back.** Memory, process-count, kill-on-close, and CPU limits are queried with `QueryInformationJobObject` before launch, and a mismatch fails closed.

The same review is candid about what remains:

- Windows Jobs are "resource containment, not a hostile-code security sandbox." The candidate keeps the host user's filesystem and network rights.
- Native Darwin limits are not aggregate enforcement and stay `verified=False`.
- The Docker fallback has no per-launch read-back.
- "Linux mocks and source contracts cannot validate Seatbelt syntax, Windows P/Invoke ABI, enforcement, or forced wrapper death."

The macOS/Windows CI job (`platform-smoke.yml`) still smoke-tests only the gate CLI. `cli_check.py` still states "Sandbox repair requires Linux with systemd and cgroup v2."

**Verdict: failed → shaky.** The code defects are fixed, but no native execution evidence exists. The accurate claims are:

- The **pre-flight gate CLI** runs natively on macOS, Linux, and Windows (CI-tested).
- **Contained sandbox repair** is Linux-only.
- macOS and Windows adapters are hardened and fail closed, but are unvalidated on their own hosts. Windows provides resource limits, not a security boundary.

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

**Verdict: held.** Count is not coverage, though. At `82c0b8e`, the macOS adapter's tests all passed while its preflight could not even compile. A high count can coexist with a non-functional path.

**Technical depth score: 17/20 (Strong).** The Linux containment is genuinely Pinnacle-grade: kernel read-back plus adversarial probes. The score is held back by:

- no seccomp filter
- partial P06 and open P08
- non-Linux adapters that have no native execution evidence
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
| Technical depth | 20 | **17** | Strong | No seccomp; P06 partial, P08 open; non-Linux adapters unvalidated natively |
| Demo & presentation | 25 | **18** | Strong | Narrated video not recorded; storyboard and voiceover diverge |
| **Total** | **100** | **72** | | |

For comparison, the October 27 [internal assessment](HACKATHON_SCORE_ASSESSMENT.md) scored **55/100**. Most of the gain comes from live Meta trials and replays (+11 tooling) and a firsthand account plus the wrong-fix corpus (+4 impact).

## Highest-value remediation before submission

Ranked by points recoverable per hour:

1. **Record and mux the voiceover** onto the rough cut, then link it on Devpost. Demo: up to +4.
2. **Run Meta on the unfamiliar-defect corpus** (`make evaluate` with `META_API_KEY`). Even 2 trials × 10 cases would answer objection 2.1. Tooling: up to +3.
3. **Fix `backend_perfection_edges.py`** to treat the P07 rejection as a pass and continue to the P04 stop probe. Commit the output as an evidence record. Technical: +1.
4. **Run the hardened adapters on real macOS and Windows hosts** and commit the probe output. `ef54542` fixed the code defects, but only a native run can validate Seatbelt syntax and the Job Object ABI. Until then, keep "Linux-only sandbox repair" in all copy.
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

---

# Round 2

Date: November 3, 2026. Assessed revisions: `55e9bff` (the head the rebuttals were submitted against) and `f143778` (current `main`, which fast-forwards from it). Same rubric, same rules: a rebuttal counts only if code, a test run, or a committed record supports it.

**Bottom line: 73/100, up 1.** Every number in the rebuttal brief reproduced. But four of the five rebuttals land in Technical depth, which was already at 17 of 20, and none of them touches the three gaps that cost the most in Round 1:

- the narrated video
- a Meta run beyond one scenario
- any user or impact evidence

The panel also found a problem Round 1 missed: the hosted **Verify** workflow has failed on every commit since `7ec953f`, 13 in a row. That includes the Round 1 revision `82c0b8e`, which Round 1 checked only locally, and both revisions assessed here. The new required `make integration` CI step has therefore never run on a GitHub runner.

## The panel

- **Meta AI Judge.** Scores against the rubric and asks what Meta's model is doing.
- **Enterprise SRE Contrarian.** Asks whether it runs, on what, and whether the gates are actually enforced.
- **DevRel Critic.** Asks what a judge sees in three minutes and whether the narration matches it.

## Baseline reconciliation

The Round 2 brief quoted Round 1 sub-scores of 18 / 21 / 18 / 15. The committed Round 1 scorecard above records **18 / 19 / 17 / 18**. Both total 72. This round re-scores from the committed record.

The brief also referred to "8 objections." Round 1 recorded **13** across the four criteria. The brief's five submissions are treated as rebuttals and mapped to the objections they answer (R2.1–R2.5). One new objection was raised (R2.6). The status of all 13 Round 1 objections is carried forward in [a table](#round-1-objections-after-round-2).

## Verification run for Round 2

Both revisions were tested in this worktree after `npm ci` in all three packages. Each `make integration` run was started after checking that no other worktree was running isolated tests. One caveat: on `f143778`, a `make check` from another worktree started while integration was running. Ours still passed, but the overlap Round 1 described could have produced a spurious failure in theirs.

| Command | `55e9bff` | `f143778` |
| --- | --- | --- |
| `make check` | **Exit 0.** Orchestrator/CLI **1,450 passed** (3 skipped), backend/root **328** (23 skipped), runner unit **134**: **1,912**. Strict mypy reports no issues in 104 source files (38 + 66). Ruff, provenance, all builds, and both distributions also passed. | **Exit 0.** Orchestrator/CLI **1,453** (3 skipped), 328, 134: **1,915**. Same lint, type, and build results. |
| `make browser` | **Exit 0.** Inspector **52**, storefront **2** | **Exit 0.** 52 + 2 |
| `make integration` (`FAULTLINE_REQUIRE_ISOLATED_TESTS=1`) | **Exit 0.** **77 passed, 0 skipped** across all four required files | **Exit 0.** **77 passed, 0 skipped** |
| Total | **2,043** | **2,046** |
| `pytest --collect-only` | `test_isolation_fuzz.py`: **82**; `test_policy_ast_fuzz.py`: **94** | unchanged |
| `backend_perfection_edges.py` re-run | Identical to the `a49c70f` record except one entry: `policy.alias_recursion` now returns `(True, False, "Exception analysis exceeded recursion limits")` instead of raising `RecursionError` | `f143778` committed that same change, plus a `build.P08` entry, to the [record](../evidence/2026-11-03-backend-perfection-edges.json) |
| Hosted **Verify** (`check.yml`) | **Failure** (run 41679971549): `make check` reports `1 failed, 1446 passed, 6 skipped` | **Failure** on `main`: `1 failed, 1449 passed, 6 skipped` |

The hosted failure is the same on every run since `7ec953f`: `test_project_run.py::test_browser_scope_and_kernel_artifact_production_limits` raises `TimeoutError`. It comes from the 5-second `asyncio.timeout` that waits for the scoped Node artifact-writer to print (`test_project_run.py:793`). The test passes locally, inside `make check` and inside `make integration`. The cause on the runner was not diagnosed in this review.

The test was added in `26b032e`, as part of the P06 partial fix, and has never passed on a hosted runner. It also predates the P08 change: `7ec953f` merged `26b032e` and failed this way before `6fcf78b` added the bubblewrap install step. Because `make check` fails first, the `make integration` step that `6fcf78b` added to `check.yml` has never executed on a hosted runner either.

## Rebuttals

### R2.1 Cross-platform isolation (answers objection 3.2)

**Claim:** Native Darwin (`sandbox-exec` + POSIX limits) and Windows (Job Objects + PowerShell) adapters exist, CLI capability detection is wired, and 82 cross-platform fuzz tests pass.

**Evidence:**

- **Adapters.** `app/isolation/darwin.py` and `windows.py` are selected by `select_runtime` (`app/isolation/__init__.py:23`). The controller uses it when `FAULTLINE_RUNTIME=isolated` (`main.py:268-271`).
- **Capability detection.** `portable.platform_capabilities()` (`portable.py:173`) names the engine, its mode, whether the native tool is present, and whether a Docker fallback exists. Its docstring says it "never launches a process or claims enforcement." `faultline version`, `doctor`, and `status` print it (`cli.py:216`, `:232`, `:390`).
- **`faultline run` still refuses non-Linux hosts.** It exits 30 with "full sandbox repair is not available on {host}" (`cli.py:1851-1862`). `cli_check.sandbox_readiness()` still reports "Sandbox repair requires Linux with systemd and cgroup v2" (`cli_check.py:212-221`).
- **Fuzz suite.** The 82 tests in `test_isolation_fuzz.py` cover command-injection payloads, long and Unicode paths, and degenerate limits. They also check that every failure is a `RuntimeUnavailable` or `CandidateRejected`. The suite surfaced two real fail-closed fixes in `cd4be0e`:
  - `sandbox_path_unsafe` for `"`, newline, CR, or NUL in a Seatbelt profile path, any of which could have rewritten the deny-by-default profile
  - `generation_identity_invalid` for malformed generation IDs
- **No native run.** `platform-smoke.yml` still runs only `tests/test_platform_smoke.py`, which covers the gate CLI. Neither adapter has run on its own host.

**SRE Contrarian:** These 82 tests run on Linux with `sys.platform` and `portable.IS_WINDOWS` monkeypatched. They check argv, profile text, and error types. Your own [adapter review](../../services/repair-orchestrator/app/isolation/ADVERSARIAL_REVIEW.md) says Linux mocks "cannot validate Seatbelt syntax, Windows P/Invoke ABI, enforcement, or forced wrapper death." Round 1 asked for a native run, and there isn't one.

**Meta AI Judge:** A judge on a Mac who runs `faultline doctor` gets an honest engine line, and `faultline run` tells them plainly that repair is Linux-only. That is the right behavior. It just isn't cross-platform repair.

**Verdict: shaky (unchanged).** The injection hardening is real, and the capability reporting is truthful. The claim still cannot go past "adapters exist, fail closed, and are fuzz-tested on Linux; not validated natively."

### R2.2 Backend isolation P01–P08 (answers objection 3.3)

**Claim:** P01–P05, P07, and P08 are closed. P08 was closed with Makefile dependency edges, a four-file `make integration` under `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`, and CI workflow updates.

| ID | Round 1 | Round 2 (`f143778`) | Proof |
| --- | --- | --- | --- |
| P01, P02, P03, P05 | Fixed, probe | **Fixed, probe** | [Security-hardening record](../evidence/2026-11-03-backend-security-hardening.json), unchanged |
| P04 | Fixed, regression tests only | **Fixed, probe-confirmed** | `runtime.stop_timeout.scope_release_attempted: true` in the [edge record](../evidence/2026-11-03-backend-perfection-edges.json) |
| P06 | Partly fixed | **Partly fixed** | The fixture path's Next.js frontend and Playwright runner still run unscoped on the host. The brief correctly leaves P06 out. |
| P07 | Fixed, regression tests only | **Fixed, probe-confirmed** | `snapshot.extra_file_admitted: false`, reason `snapshot_nonapplication_file`. The verify-then-mount race remains. |
| P08 | Open | **Fixed in configuration, verified locally, not yet green in hosted CI** | See below |

**P08 evidence:**

- **Build ordering.** `Makefile:33` adds the edge `test: frontend runner inspector`, so `make -j check` cannot start Python tests before the three builds finish.
- **Four-file integration.** `Makefile:17-18` runs all four required files with the flag set.
- **CI wiring.** `check.yml` installs bubblewrap, asserts that cgroup v2 and `systemd-run` are present, and runs `make integration` with `FAULTLINE_REQUIRE_ISOLATED_TESTS: 1`. `faultline-ci.yml` sets the variable at job scope.
- **Probe.** The edge record's `build.P08` entry checks the dependency edge under parallel make and intercepts the integration recipe. It observed the required flag and all four file arguments.
- **Local run.** 77 passed, 0 skipped, on both revisions.

**SRE Contrarian:** P08 was "CI does not require live containment paths." You fixed it by adding a required step to a workflow that has now failed on 13 consecutive commits. That step has never run on a hosted runner. A required step that is never reached is not enforcing anything yet.

**Meta AI Judge:** The configuration is correct, and the probe checks the right things. The red build is a separate test that was failing before P08 changed. It blocks the proof, not the fix.

**SRE Contrarian:** It is a separate test, but not an unrelated one. It is P06's own kernel-limit test, the evidence for the browser scope. It has never passed outside this machine.

**Verdict:**

- **Held** for P01–P05 and P07.
- **Partly fixed** for P06.
- **Shaky** for P08 until a hosted Verify run is green through `make integration`.

The defensible statement is: *"Seven of eight findings are fixed. P01–P05 and P07 are confirmed by re-running the audit's probes. P08's build ordering and required integration gate are in place and verified locally; hosted CI has not yet passed it. P06 is partly fixed."*

### R2.3 AST policy hardening (supports objection 2.4 and the audit's "AST resource edge")

**Claim:** `policy.py` was hardened against lone-surrogate UTF-8 crashes and deep alias recursion, with 94 new fuzz tests.

**Evidence:**

- **Alias recursion.** `validate_ast` now catches `RecursionError` around alias resolution and every gate. It returns `(True, False, "Exception analysis exceeded recursion limits")` (`policy.py:400-411`).
  - Before: the helper raised, and `PatchPolicy.validate` labeled a syntactically valid source `syntax_valid=false`. The audit's "Controls and edge cases that held" section recorded that mismatch.
  - Now: both levels agree, and the edge record shows the new result.
- **Lone surrogates.** `PatchPolicy.validate` checks UTF-8 size before hashing against `base_sha256` (`policy.py:474-480`). Before, a lone surrogate escaped the gate as an unhandled `UnicodeEncodeError` instead of the canonical rejection. This review found no evidence that it could ever admit a patch; it was a crash, not a bypass.
- **Fuzz suite.** The 94 tests in `test_policy_ast_fuzz.py` cover:
  - shadowed handler names (match, walrus, comprehensions, `with`, PEP 695 aliases)
  - suppression through `finally` and `except*`
  - homoglyph and NFKC identifiers
  - a seeded adversarial corpus that must fail closed through `PatchPolicy.validate`

**Meta AI Judge:** This gate is what stands between `muse-spark-1.3` output and the sandbox, so it matters to the Meta story. But fuzzing the gate is not evidence about what Meta's model produces.

**DevRel Critic:** No judge will see this in three minutes. It belongs in the technical write-up, not the pitch.

**Verdict: held.** The boundary from Round 1 still applies: AST checks are policy, not a sandbox.

### R2.4 Inspector polish and evidence feedback (offered against objection 4.1)

**Claim:** A live candidate pulse badge with candidate-index tracking and an auto-scroll event log with a padlock indicator were added, and 52 Inspector browser specs pass.

**Evidence:**

- **Candidate badge.** It renders "Candidate N of up to `CANDIDATE_BUDGET`" during step 3 (`JobResult.tsx:44-61`).
- **Pulse.** The pulse is `aria-hidden`, and a spec asserts that (`inspector.spec.ts:1251`).
- **Auto-scroll lock.** The toggle keeps the log on its newest event, and the padlock shows the lock state (`Evidence.tsx:429-477`, `globals.css:661`). A spec drives the toggle (`inspector.spec.ts:1274`).
- **Specs.** 52 Inspector specs pass.

**DevRel Critic:** Both features shipped in `1f27e8c`, an ancestor of the Round 1 revision `82c0b8e`. Round 1 already counted 52 Inspector specs. This is not new work since Round 1, and the Round 1 demo deduction was the missing video, not the UI.

What did change since Round 1 is the [voiceover](../VOICEOVER_SCRIPT.md) (`149f78d`). It now narrates the pulse, the auto-scroll log, and the holdout result with a "non-Meta" label. Two gaps remain:

- The storyboard's Apply and Revert cues (`VIDEO_STORYBOARD.md:22-23`) still have no narration.
- "Thirty interactive elements" is still marked "Owner to confirm" (`VOICEOVER_SCRIPT.md:25`).

**Verdict: held** as a feature. **Failed** as a rebuttal to 4.1: it is not new, and the video still does not exist.

### R2.5 Test depth (answers objection 3.4)

**Claim:** The suite grew from 1,754 to 1,912 automated tests in `make check`. With 54 browser and 77 integration tests, that is 2,043 passing test executions across 104 source files with zero type errors.

**Evidence:** Reproduced exactly on `55e9bff`; see the [verification table](#verification-run-for-round-2). On `f143778` the figures are 1,915 and 2,046. The comparison needs fixing, though:

- **1,754 was not a `make check` figure.** It was `make check` (1,700) plus browser (54) at `82c0b8e`.
- **Like for like:** `make check` went from 1,700 to 1,912 (+212), and the total went from 1,754 to 2,043 (+289).
- **Integration was not run in Round 1.** 77 of the +289 are integration tests that Round 1 did not run.

**SRE Contrarian:** You can run 2,043 tests locally. On the same commit, GitHub's runner shows one failure. Lead with the number a judge can check by clicking. Round 1's warning also still applies: a high count can coexist with an unvalidated path. All 82 cross-platform fuzz tests run on Linux.

**Verdict: held** for the count. **Shaky** for any "fully green" framing while hosted Verify is red.

### R2.6 New objection: "Your CI is red." (SRE Contrarian)

**Evidence:** `gh run list --workflow Verify` shows the following, oldest first:

- **Last green run:** `3453dd6`.
- **Every commit since has failed:** `7ec953f`, `bedddcc`, `82c0b8e`, `ef54542`, `8630a24`, `a615794`, `d838efa`, `a49c70f`, `6fcf78b`, `8ce816f`, `55e9bff`, `f143778`, and `e65ee97`.

Each failure is the one test named [above](#verification-run-for-round-2), added in `26b032e`. Round 1 reported only local runs and did not check hosted CI. That was a gap in the Round 1 review, and it is corrected here. `README.md:5` shows a hardcoded green "tests 1,530 passing" badge that links to the Actions page where these failures are listed.

**Verdict: failed** as of this review. It doesn't change any finding about the engine, but it is the first thing a skeptical judge who clicks through will see. It also undercuts the P08 rebuttal.

## Round 1 objections after Round 2

| # | Objection | Round 1 | Round 2 | What changed |
| --- | --- | --- | --- | --- |
| 1.1 | Prove revenue protection | shaky | **shaky** | Nothing |
| 1.2 | Firsthand or backfilled story | shaky | **shaky** | Nothing |
| 1.3 | Is this production monitoring | held | **held** | Nothing |
| 2.1 | Is Meta doing the work | held / shaky | **held / shaky** | No new Meta evidence since October 31; still no Meta corpus run |
| 2.2 | Llama 3.3 70B run | failed / held | **failed / held** | Nothing |
| 2.3 | Prompt containment vs full repo | shaky | **shaky** | Nothing |
| 2.4 | Verifier-guided repair | held / shaky | **held / shaky** | The policy gate is hardened (R2.3); still no Meta behavioral retry |
| 3.1 | Is it a real sandbox | held | **held** | Still no seccomp filter |
| 3.2 | Native macOS / Windows isolation | failed → shaky | **shaky** | Injection hardening and truthful capability reporting; no native run (R2.1) |
| 3.3 | P01–P08 really fixed | failed | **held** (P01–P05, P07), **partly fixed** (P06), **shaky** (P08) | Probes now confirm P04 and P07, and P08 is configured (R2.2) |
| 3.4 | Is the test count real | held | **held** | 2,043 reproduced; hosted CI red, including on Round 1's revision (R2.5, R2.6) |
| 4.1 | Is the pitch reproducible | shaky | **shaky** | Voiceover refreshed; video still not recorded |
| 4.2 | Stage failure fallbacks | held | **held** | Nothing |
| 4.3 | Narration overclaims | failed → corrected | **corrected** | "Thirty interactive elements" still unsourced |

## Re-scoring debate

### Impact: 18/30 (unchanged)

**DevRel Critic:** A gate that runs natively on three operating systems widens who can try it.

**Meta AI Judge:** That was already true in Round 1, and it was already scored.

None of the five rebuttals adds a user, a measured saving, or a second route. `IMPACT_EVIDENCE.md`'s feedback table is still empty.

**Settled: 18.**

### Meta AI tooling: 19/25 (unchanged)

**Meta AI Judge** argued for +1, on the grounds that the hardened gate is part of the "validation" the Pinnacle band describes. The other two judges disagreed, and the panel agreed with them:

- **SRE Contrarian:** None of the five rebuttals involves a Meta call. The newest Meta evidence is still the October 31 ledger.
- **DevRel Critic:** Hardening the gate is Technical depth, and it is scored there. Counting it again here would double-count.

**Settled: 19.**

### Technical depth: 18/20 (+1)

Round 1 withheld three points for four reasons. Their status now:

| Round 1 deduction | Round 2 status |
| --- | --- |
| Broken audit probe | **Cleared.** The probe runs, and its record confirms P04, P07, and P08's configuration. |
| P08 open, P06 partial | **Mostly cleared.** P08 is configured and passes locally but is not green in CI. P06 is still partial. |
| Non-Linux adapters unvalidated natively | **Still open.** |
| No seccomp filter | **Still open.** |

The two fuzz suites (176 tests) found and fixed four real fail-closed gaps:

- Seatbelt profile injection
- malformed generation IDs
- alias recursion
- lone-surrogate crashes

**Meta AI Judge** argued 19. **SRE Contrarian** argued 17: a required gate that has never passed on a hosted runner makes operability worse, not better. The panel settled at **18**. Hosted Verify was already red at the Round 1 revision, so Round 1's 17 did not account for it. This round's +1 already counts against it.

- **Path to 19:** a green hosted Verify run through `make integration`.
- **Path to 20:** a native macOS or Windows adapter run, or a seccomp filter.

### Demo and presentation: 18/25 (unchanged)

**DevRel Critic:** The Inspector features existed in Round 1. The video still doesn't. A refreshed script with nothing recorded earns nothing.

**SRE Contrarian** proposed −1, because the red CI is visible to any judge. The panel declined: Demo scores the presentation, and the CI failure is already counted under Technical depth (R2.6).

**Settled: 18.**

## Round 2 scorecard

| Criterion | Weight | Round 1 | Round 2 | Change | Main remaining deduction |
| --- | ---: | ---: | ---: | ---: | --- |
| Impact | 30 | 18 | **18** | 0 | No users, no measured savings, one route, uncorroborated anecdote |
| Meta AI tooling | 25 | 19 | **19** | 0 | 3/3 trials on one scenario; no Meta corpus run, behavioral retry, or Llama run |
| Technical depth | 20 | 17 | **18** | +1 | Hosted Verify red; no seccomp; P06 partial; non-Linux adapters unvalidated natively |
| Demo & presentation | 25 | 18 | **18** | 0 | Narrated video not recorded; Apply/Revert cue unnarrated |
| **Total** | **100** | **72** | **73** | **+1** | |

The engineering work this round was real, but almost all of it landed in the criterion that had the least room left. The remaining 27 points sit almost entirely in Impact, Meta tooling, and Demo, and the engine cannot move those scores any further.

## Highest-value remediation before submission (updated)

Ranked by points recoverable per hour:

1. **Make hosted Verify green.** Diagnose why `test_browser_scope_and_kernel_artifact_production_limits` times out on `ubuntu-latest`, then confirm `make integration` passes on a hosted runner. Technical: +1. It also removes the easiest hostile question. Do **not** skip or xfail the test to get green. That would hide exactly the containment path P08 is about.
2. **Record and mux the voiceover**, narrate the Apply and Revert cues, and link the video on Devpost. Demo: up to +4.
3. **Run Meta on the unfamiliar-defect corpus** (`META_API_KEY=… ./scripts/evaluate.sh --suite holdout --repeat 2`). Tooling: up to +3.
4. **Collect even two real user conversations** for `IMPACT_EVIDENCE.md`. Impact: up to +3.
5. **Run the macOS and Windows adapters on native hosts** and commit the probe output. Technical: the last point.
6. **Source or cut "thirty interactive elements,"** and re-pin the spoken test count to the submitted commit. The voiceover's "1,872" is accurate only for `a49c70f`.

## Rehearsal defense notes

Spoken answers should take 20 seconds or less, and each one should point at a proof. If an answer doesn't fit, say the defensible sentence and offer the record.

**"Does repair run on my Mac or Windows machine?"**
- **Say:** "The pre-flight gate runs natively on macOS, Linux, and Windows, and CI tests it on all three. Sandbox repair is Linux-only today. The macOS and Windows adapters exist, fail closed, and are fuzz-tested, but we haven't run them on native hosts, so we don't claim them."
- **Show:** the `faultline doctor` engine line, then `faultline run` exiting 30 on a non-Linux host.
- **Never say:** "native isolation on all three platforms."

**"Your CI is red."** (Fix this before submitting if at all possible.)
- **Say:** "One test, the browser artifact-limit test, times out on GitHub's Ubuntu runners. It passes locally, including in the full 77-test isolated integration suite with skips disallowed. We haven't skipped it, because skipping it would hide the exact containment path that audit finding P08 is about."
- **Never say:** "CI is green" or "flaky."

**"How many tests?"**
- **Say:** "2,043 on commit `55e9bff`: 1,912 in `make check`, 54 browser, and 77 isolated integration with no skips allowed." On `f143778`, the figure is 2,046.
- **Never say:** "2,043 passing in CI."

**"Did you fix all eight audit findings?"**
- **Say:** "Seven of eight. Re-running the audit's own probes confirms P01 through P05 and P07. P08's build ordering and required integration gate are in place and verified. P06 is partly fixed: the fixture path's frontend and runner still run unscoped on the host."
- **Show:** the [edge record](../evidence/2026-11-03-backend-perfection-edges.json).

**"What did fuzzing actually find?"**
- **Say:** "Four fail-closed gaps:
  - a Seatbelt profile path that could inject rules
  - malformed generation IDs
  - an alias chain deep enough to overflow the resolver
  - a lone surrogate that crashed the hash check

  Each now returns a canonical rejection."
- **Never say:** "fuzzing proves the gate is secure." AST checks are policy, not a sandbox.

**"Is Meta doing the work?"** (unchanged from Round 1)
- **Say:** "Three of three live `muse-spark-1.3` trials verified 44 of 44 checks on the first attempt. That's one scenario. The holdout corpus has only been run with a labeled non-Meta model."
- **Never say:** "superior to full-repo context."

**"What's new in the Inspector?"**
- **Say:** "A live badge shows which candidate the sandbox is verifying, out of the two-attempt budget, and the event log follows the run unless you scroll up."
- **Never say** that these are new since the last review if asked about timing. They shipped in `1f27e8c`.

**"Why should this score higher than last time?"**
- **Say:** "We hardened the engine and closed audit findings with probes. What's left is the video, a Meta corpus run, and user evidence. We'd rather show you what's measured than claim what isn't."

## Documentation corrections (Round 2)

These were made in the same change as this round:

- [`DEVPOST_SUBMISSION.md`](../DEVPOST_SUBMISSION.md):
  - The build-verification row and the test-count bullet now cite the `f143778` figures, including `make integration`, and state that hosted Verify is not yet green.
  - The P01–P08 row and the Limits paragraph now say P08 is fixed in configuration and verified locally, instead of "open."
- [`PROJECT_STATUS.md`](../PROJECT_STATUS.md):
  - The verification bullets now carry the `f143778` counts.
  - The audit-findings bullet no longer says P04 and P07 lack probe evidence, that P08 is open, or that the edge probe needs updating.

These were flagged and left unchanged:

- **The `README.md:5` badge.** It is a hardcoded "1,530 passing" badge. Replace it with the live Verify workflow badge once CI is green. That choice belongs to the owner.
- **The voiceover's "1,872"** (see remediation 6).
