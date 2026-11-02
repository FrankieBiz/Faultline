# Faultline execution layer: independent systems security audit

**Date:** 2026-11-02

**Audited source:** `23ea6f6c7e61723ffac6a28a7af79a61878a0a14`

**Scope:** candidate execution, Bubblewrap profiles, cgroup v2 quotas, subprocess supervision, signals, reaping, temporary storage, network boundaries, concurrency, and platform fallback behavior. This is an assessment and mitigation plan; no runtime fixes were applied.

## Executive assessment

Faultline has a substantial, functioning Linux containment boundary. On the audit host, the actual backend profile hid the home directory and sysfs, mounted source and dependencies read-only, separated network and user namespaces, dropped effective capabilities, enabled no-new-privileges, and bounded writable temporary filesystems. Real cgroup enforcement tests killed memory hogs and stopped task creation. Missing sandbox prerequisites do not automatically trigger host execution. Cleanup confirmation and quarantine are meaningful protections, rather than cosmetic status fields.

There are nevertheless two **High** findings: the universal project's interpreter-discovery mount can expose files deliberately excluded from its snapshot, and the project browser's origin filter permits WebRTC traffic into the host network. Both were reproduced with synthetic files or loopback-only traffic. Neither required a kernel exploit. The first requires control of the pre-existing project/dependency layout; it is not achievable merely by changing any arbitrary single repair target. The second is reachable by JavaScript served by an untrusted project.

Host helper ownership is also incomplete: a detached descendant survives normal supervisor shutdown, direct SIGTERM to the supervisor bypasses cleanup, and only its immediate child is reaped. These defects do **not** establish an escape from the candidate's PID namespace or cgroup: the corresponding namespaced detached-process probe cleaned up successfully. Browsers and frontend helpers, however, run outside those backstops.

**Decision:** the tested backend is a credible containment layer for the documented single-owner workflow. The entire execution stack should not be represented as providing filesystem confidentiality for arbitrary project layouts or complete network isolation for arbitrary project pages. Address S-01 and S-02 before relying on those guarantees for hostile projects. No unrestricted host code execution or kernel escape was demonstrated.

The existing [orchestrator README](../../services/repair-orchestrator/README.md#aggregate-resource-limits) already discloses the shared kernel, absent seccomp filter, host abstract listener, and trusted parsers outside the candidate scope. Those are acknowledged residual risks, not discoveries of concealed guarantees. This report independently evaluates their consequences and separates them from the newly reproduced project mount and WebRTC failures.

## Method, assumptions, and limits

The review traced both execution paths: `IsolatedRuntime` for the fixed BuggyShop fixture and `ProjectRuntime` for general ReproSpec projects. It also inspected their launchers, snapshots, browser drivers, CLI/platform gates, crawler subprocesses, worker deadlines, database admission, startup reconciliation, and CI. References below identify lines in the audited revision.

The primary attacker is candidate/project code, including its HTTP responses and JavaScript. A separate, explicitly labeled scenario considers an untrusted local process on the same machine. Operator configuration, the controller installation, system binaries, dependency installation, and kernel are initially trusted. Malicious project/dependency layouts are relevant because the universal runtime executes projects and derives mounts from those layouts. Changing operator configuration or a trusted toolchain is not treated as a remote candidate exploit.

Live probes ran unprivileged on Fedora Linux, kernel `7.2.13-200.fc44.x86_64`, Bubblewrap `0.12.0`, systemd `259.10-1.fc44`, and Python `3.13.16`, with a working systemd user manager and cgroup v2. Probes used temporary synthetic data, owned processes/scopes, bounded fork/thread counts, and loopback listeners. No credential files were read; no external service was attacked. Host lifecycle probes used an audit-owned child subreaper to reclaim their deliberately orphaned descendants.

Evidence labels:

- **Reproduced:** behavior observed in an actual process, namespace, kernel quota, or browser.
- **Source-confirmed:** the implementation establishes the condition, but its full adverse impact was not induced.
- **Hardening/coverage:** a residual exposure or missing assurance, without a demonstrated exploit.

This is not a kernel exploit campaign, dependency CVE inventory, throughput certification, or native macOS/Windows test run. Eight concurrent backend sessions and 32 supervised host commands were exercised; prolonged adversarial saturation and concurrent full browser generations were not. Existing passing tests do not negate the independently reproduced findings.

## Execution and trust boundaries

```text
Controller / durable worker / model credentials                   HOST
  |-- ManagedProcess -> Python supervisor (liveness pipe)
  |     |-- systemd-run --user --scope -> env -i -> bwrap
  |     |     `-- namespace init -> trusted launcher -> candidate  CANDIDATE SCOPE
  |     `-- Node frontend or Node/Chromium driver                 HOST, UNSCOPED
  |-- HTTP bridge on host loopback
  `-- bounded HTTP transport -> inherited abstract UDS listener
```

The listener deliberately crosses the candidate network boundary. In the fixture, Uvicorn uses that inherited descriptor directly. In the project runtime, the trusted launcher accepts the descriptor and relays to `127.0.0.1:8765` inside the namespace; the project command does not inherit the listener. Namespace-local loopback is distinct from host loopback.

The browser driver is trusted code, but the pages it interprets are not. Candidate response limits constrain HTTP bytes, not the work those bytes can cause in the browser. Cgroup resource provenance currently describes the candidate scope, not the entire job tree.

Key implementation references:

| Boundary | Source |
| --- | --- |
| Namespace profile and cgroup wrapping | [`isolated_runtime.py:551–648`](../../services/repair-orchestrator/app/isolated_runtime.py#L551-L648) |
| Kernel readback, process membership, scope release | [`isolated_runtime.py:690–763`](../../services/repair-orchestrator/app/isolated_runtime.py#L690-L763) |
| Backend resource limits and Uvicorn entry | [`isolated_backend.py:26–53`](../../services/repair-orchestrator/app/isolated_backend.py#L26-L53) |
| Process ownership and bounded output | [`isolated_runtime.py:323–412`](../../services/repair-orchestrator/app/isolated_runtime.py#L323-L412) |
| Liveness supervisor | [`process_supervisor.py:16–40`](../../services/repair-orchestrator/app/process_supervisor.py#L16-L40) |
| Project mounts and entry | [`project_runtime.py:110–166`](../../services/repair-orchestrator/app/project_runtime.py#L110-L166), [`project_launcher.py:38–63`](../../services/repair-orchestrator/app/project_launcher.py#L38-L63) |
| Project browser policy | [`repro_browser.mjs:8–20`](../../services/repair-orchestrator/app/repro_browser.mjs#L8-L20) |

## Findings, ranked

| ID | Severity | Finding | Evidence |
| --- | --- | --- | --- |
| S-01 | High | Interpreter discovery can add an unintended host-directory mount | Reproduced |
| S-02 | High | Project browser WebRTC bypasses the origin-based network policy | Reproduced |
| S-03 | Medium | Fixture/crawler Chromium launches disable its sandbox by default | Source-confirmed; no browser exploit attempted |
| S-04 | Medium | Host process ownership does not cover detached children, supervisor signals, or descendant reaping | Reproduced |
| S-05 | Medium | Candidate quotas leave host helpers and artifact production outside a job-wide budget | Source-confirmed |
| S-06 | Medium, local threat | Abstract UDS and loopback bridges lack a local peer authentication boundary | Source-confirmed |
| S-07 | Medium, deployment concurrency | API startup reconciliation can terminate another active owner | Scoped reproduction plus source trace |
| S-08 | Low | Frontend port selection has a bind/release/rebind race | Source-confirmed |

### S-01 — Interpreter discovery exposes an unintended host directory

**Impact:** project-controlled filesystem layout can expose host files that were never admitted to the candidate snapshot, undermining confidentiality while leaving the mount read-only.

`ProjectRuntime._sandbox()` rejects a symlink for the top-level `.venv` dependency directory, but separately resolves `.venv/bin/python`, takes its grandparent, checks only for `bin` and `lib` directories, then mounts that entire prefix at its original absolute host path. It does not establish that the resolved file is an approved interpreter or that its prefix is an approved distribution. See [`project_runtime.py:129–141`](../../services/repair-orchestrator/app/project_runtime.py#L129-L141).

**Reproduction:** in a temporary project, create ordinary directories `.venv/bin`, `bin`, and `lib`; create a synthetic ordinary `bin/python` file; point `.venv/bin/python` to `../../bin/python`. Put `audit-private-marker.txt` at project root and export a separate, empty snapshot. Launch the unchanged project sandbox profile with trusted `/python/bin/python3.13`, without executing the synthetic interpreter. The sandbox reads the marker via the project root's absolute path:

```json
{"unexported_marker_visible": true, "value": "synthetic nonsecret data excluded from export\n"}
```

The mount succeeds because the resolved interpreter's grandparent is the original project root. Consequently the normal snapshot exclusion rules are bypassed for that entire directory. The probe did not read actual secret files. A real project root may contain private untracked files or controller run data. A different selected prefix can expose another readable directory if its shape satisfies the same checks.

**Conditions and limits:** an attacker must influence the existing project/dependency layout; the standard model patch policy cannot create this structure through an unrelated one-file source patch. The mount is read-only, so this is not a demonstrated host-write primitive. Independently, complete `.venv` and `node_modules` mounts may contain operator-private material and are live dependencies rather than content-addressed exports.

**Mitigation:** derive interpreter mounts from controller-owned configuration and approved distribution identities, never a candidate-supplied symlink. Verify the executable and canonical prefix against an explicit allowlist outside the project and run-data trees; reject ambiguous distributions. Stage a minimal, immutable runtime/dependency image with a manifest and dedicated mount points. Add a regression using the layout above and a harmless marker outside the snapshot. Read-only access must not be equated with confidentiality.

### S-02 — WebRTC crosses the project browser's network boundary

**Impact:** candidate JavaScript can generate host-network traffic despite the driver's claim that only the loopback application origin receives browser traffic.

The actual project driver launches Chromium on the host, allows only one origin through `context.route('**/*')`, blocks service workers, and closes routed WebSockets. These are useful HTTP/WebSocket policies, but they are not an operating-system network sandbox. See [`repro_browser.mjs:1–20`](../../services/repair-orchestrator/app/repro_browser.mjs#L1-L20) and host launch at [`project_runtime.py:355–363`](../../services/repair-orchestrator/app/project_runtime.py#L355-L363).

**Reproduction:** run the unchanged `repro_browser.mjs` against a temporary HTTP fixture on host loopback. Serve a page containing the following script, with an independently owned UDP listener substituted for `PORT`. Send the driver's normal `navigate` action and observe the UDP listener for 1.5 seconds.

```javascript
window.pc = new RTCPeerConnection({
  iceServers: [{ urls: 'stun:127.0.0.1:PORT' }]
});
pc.createDataChannel('audit');
pc.createOffer().then(offer => pc.setLocalDescription(offer));
```

Observed through the real driver, with Chromium sandboxing enabled:

```json
{"browser_ready":true,"navigation":{"result":null},"host_loopback_stun_packets":3}
```

Thus a project page can reach a host UDP endpoint outside the allowed HTTP origin. No remote destination, data exfiltration, TCP SSRF, or host-code execution was tested. The demonstrated primitive is host-network UDP/STUN traffic. External reachability depends on host routing and firewall policy.

**Mitigation:** place the browser and its driver in a separate network namespace/container with no host/LAN/Internet route and an explicit connection to the job bridge. Enforce egress at that boundary, including UDP, IPv6, DNS, and WebRTC. Disable unneeded WebRTC as additional defense, but do not make browser flags or Playwright routing the sole network boundary. Keep assertion logic and credentials outside the browser compartment. Add the loopback STUN test alongside forbidden HTTP, WebSocket, redirect, service-worker, and IPv6 tests. Playwright's routing documentation describes browser request interception; it does not establish kernel-level egress isolation. [Playwright network documentation](https://playwright.dev/docs/network).

### S-03 — Inconsistent Chromium sandbox policy

The project driver explicitly uses `chromiumSandbox: true` and tests that launch profile before accepting work. The fixture oracle and autonomous crawler instead call `chromium.launch({ headless: true })`; the fixture readiness probe does the same. See [`oracle.ts:537–553`](../../tools/browser-runner/src/oracle.ts#L537-L553), [`crawler.ts:921`](../../tools/browser-runner/src/crawler.ts#L921), and [`isolated_runtime.py:912–920`](../../services/repair-orchestrator/app/isolated_runtime.py#L912-L920).

The locked Playwright `1.64.1` implementation adds `--no-sandbox` unless `chromiumSandbox === true`; this was checked in the installed package as well as the official API reference. Chromium sandboxing defaults to false. [Playwright BrowserType launch options](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox).

This is a defense-in-depth weakness, particularly for the crawler's arbitrary pages. Browser exploitation was not attempted; visiting a malicious page alone is not proof of native host execution. The fixed fixture's narrower trusted UI reduces exposure compared with universal project pages, but it still interprets candidate-supplied content. Neither fixture browser setup establishes a complete outbound-network restriction.

**Mitigation:** explicitly enable Chromium sandboxing for all production launches and preflight the exact profile used for execution. Fail closed when unavailable. Combine this with the browser compartment and quotas in S-02/S-05; do not introduce an automatic `--no-sandbox` fallback. Test caller-provided browser instances separately because launch policy is then owned by the caller.

### S-04 — Supervisor shutdown does not establish complete host process cleanup

The liveness-pipe design is valuable: the controller owns the write endpoint, children do not inherit it, cancellation closes it, and controller death can trigger cleanup independently of Python `finally` blocks. Output is drained and capped. Normal EOF sends SIGTERM to the immediate command's process group, permits up to one second, then SIGKILLs that group and waits for the immediate child.

However, [`process_supervisor.py:20–40`](../../services/repair-orchestrator/app/process_supervisor.py#L20-L40) neither installs termination handlers nor becomes a child subreaper, and a process group is not a descendant-ownership boundary.

Three bounded live probes showed:

1. A host command spawned a sleeping child using `start_new_session=True`. After normal `ManagedProcess.stop()`, the supervisor had exited with status `143`, but the detached child was still alive. Its standard streams were redirected so pipe EOF could not mask the ownership gap.
2. Sending SIGTERM directly to the supervisor, then calling `stop()`, produced `TimeoutError` after the four-second stop deadline. The immediate child remained alive and retained the output pipes. Direct supervisor SIGINT is also not explicitly handled; its exact interruption behavior was not separately reproduced. Normal controller Ctrl+C/termination generally reaches liveness-based cleanup and is a different path.
3. A same-group grandchild that ignored SIGTERM was killed but remained in state `Z` after `stop()` returned, until the audit's outer subreaper called `waitpid()`. In ordinary deployments reaping is delegated to host PID 1 or another ancestor, so this does not prove permanent zombie accumulation on this Fedora host.

The existing Chromium lifecycle test explicitly permits a remaining `Z` state: [`test_isolated_runtime.py:215–223`](../../services/repair-orchestrator/tests/test_isolated_runtime.py#L215-L223). It proves no observed active descendants in that sampled tree, not local reaping of all descendants.

**Boundary qualification:** a separate candidate probe forked a child that called `setsid()` inside Bubblewrap. Normal stop plus scope release confirmed the entire scope absent. PID-namespace teardown and cgroup cleanup remain effective backstops for that case. The kernel kills remaining members when a PID namespace's init exits. [Linux PID namespace semantics](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html).

**Mitigation:** put each host helper tree in an owned cgroup/service with control-group termination and verified emptiness; use a subreaper and reap adopted descendants until ownership is resolved. Turn supervisor SIGTERM/SIGINT into the same bounded cleanup state machine as pipe EOF. Catch the process-exit race around the initial `killpg(SIGTERM)`. Apply escalation to the ownership group even if the original command exits early. Require both process exit and pipe-drain completion, while retaining recoverable ownership if either times out.

The crawler has a separate, weaker lifecycle implementation: its watchdog and finalizer terminate/kill only the Node PID, without this liveness supervisor or process-group ownership ([`crawler_service.py:186–243`](../../services/repair-orchestrator/app/crawler_service.py#L186-L243)). Its Playwright cleanup can handle normal signals, but abrupt controller/runner failure lacks the same ownership guarantees. Consolidate that path into the strengthened supervisor.

### S-05 — Quotas cover the candidate, not the work it causes on the host

The verified production candidate scope has 512 MiB `memory.max`, zero swap, 64 tasks, CPU quota equivalent to one CPU, and group OOM kill. Those values are real. The controller, frontend, browser/driver, supervisor, and evidence writes are outside the candidate scope. The integration test explicitly asserts that the trusted frontend is outside it ([`test_resource_limits_cgroup.py:145–150`](../../services/repair-orchestrator/tests/test_resource_limits_cgroup.py#L145-L150)).

A small untrusted page can amplify into substantial browser allocations, renderer processes, CPU work, canvas/image decoding, or trace data. The host browser need not be compromised for this. The output transport cap is 64 KiB per backend response, not a cap on browser memory or cumulative responses. Artifact size checks occur after production of screenshots/traces ([`repro_browser.mjs:63–74`](../../services/repair-orchestrator/app/repro_browser.mjs#L63-L74), [`isolated_runtime.py:1339–1372`](../../services/repair-orchestrator/app/isolated_runtime.py#L1339-L1372)). Host temporary profiles and trace staging can therefore consume memory/disk before rejection. Multiple installations have independent limits, without a common installation-wide resource ceiling in this code.

Additionally, only the fixture launcher sets `RLIMIT_NOFILE`, `RLIMIT_CORE`, `RLIMIT_CPU`, `RLIMIT_AS`, and `RLIMIT_NPROC`. The universal `project_launcher.py` starts its command without analogous rlimits. Its mandatory cgroup still bounds memory/tasks/CPU rate, but not individual open-descriptor counts or core-dump behavior. System-wide core-dump helpers and storage policy can remain relevant even when candidate writable filesystems are private. No host exhaustion or core-dump flood was induced.

**Mitigation:** introduce a parent job/installation slice containing both candidate and separately budgeted browser/frontend/helper subgroups. Reserve controller resources independently. Set explicit per-process file-descriptor and zero-core limits in the universal launcher; retain aggregate quotas. Put browser profiles, traces, and screenshots on private quota-controlled storage; bound total job evidence and retention, not just final individual artifacts. Limit launch concurrency across installations. Distinguish candidate quota verification from whole-job resource accounting in status and evidence.

### S-06 — Host-side local IPC endpoints are discoverable and unauthenticated

Backend listeners use host-network abstract AF_UNIX addresses `\0faultline-<UUID>` ([`isolated_runtime.py:1010–1025`](../../services/repair-orchestrator/app/isolated_runtime.py#L1010-L1025), [`project_runtime.py:213–229`](../../services/repair-orchestrator/app/project_runtime.py#L213-L229)). This avoids pathname length and symlink-redirection problems. Abstract sockets have no filesystem permission boundary, however, and their names can be observed through the host's UNIX socket listing. No accept-time `SO_PEERCRED` or application authentication check is implemented. Abstract socket access is not controlled by filesystem mode bits. [Linux UNIX-domain socket documentation](https://man7.org/linux/man-pages/man7/unix.7.html).

The HTTP bridges bind to host loopback. The project bridge validates `Host`, which helps against browser-origin confusion, but a native local process can supply that value; the fixture bridge does not have the same check. Neither authenticates the local caller. A local process with access to these endpoints can submit requests that change candidate state, interfere with measurements, or occupy relay connections. Project relay handling creates one thread per accepted connection, constrained by the candidate's 64-task scope rather than a dedicated relay admission limit ([`project_launcher.py:55–62`](../../services/repair-orchestrator/app/project_launcher.py#L55-L62)).

**Limits:** this is a same-host attacker scenario, not public network exposure; no cross-UID live probe was performed. A candidate in a different private network namespace cannot simply discover/connect to another host abstract socket. Random UUIDs reduce accidental collisions, but are not local access control.

**Mitigation:** use filesystem UDS endpoints inside controller-owned mode-0700 directories, or verify peer credentials with a design that also distinguishes same-UID jobs. Authenticate host loopback traffic with per-session credentials inaccessible to candidate JavaScript, and isolate the browser-to-bridge transport. Where separate local tenants are supported, use separate service identities or compartments. Bound relay threads/connections and request lifetimes. Document a trusted-local-host assumption if that is the intended deployment boundary.

### S-07 — Startup reconciliation can kill a live peer controller

The CLI correctly takes a nonblocking per-data-directory `.run.lock` before reconciliation ([`run.py:88–115`](../../services/repair-orchestrator/app/run.py#L88-L115)). Database transactions and the singleton lease serialize job admission. Those controls do not protect the API's startup lifecycle: [`main.py:235–284`](../../services/repair-orchestrator/app/main.py#L235-L284) opens the database and starts a worker without taking that process lock.

Worker startup reconciliation can mark unfinished jobs interrupted, and runtime reconciliation treats every scope matching its installation prefix as leftover ([`worker.py:888–909`](../../services/repair-orchestrator/app/worker.py#L888-L909), [`isolated_runtime.py:754–763`](../../services/repair-orchestrator/app/isolated_runtime.py#L754-L763)). It does not establish that the previous owner has died. A second API process, or API plus CLI sharing data, can therefore invalidate an active owner's state and kill its scopes. The default API entry uses one Uvicorn worker, which reduces the ordinary deployment risk but does not enforce exclusivity against another invocation.

**Scoped reproduction:** launch an audit-owned active scope under a unique installation prefix and verify it. Construct a second runtime with the same installation identity and invoke its leftover-scope reconciliation. The first active process exits and its scope is removed. This directly verifies the destructive runtime primitive; a full two-API/database race was not executed.

**Mitigation:** acquire a common lifetime process lock on every controller entry path before database/runtime reconciliation, and refuse a second owner. Hold it through shutdown. Add a two-process startup test proving the second invocation neither edits unfinished jobs nor signals the first owner's scopes. Do not solve this by disabling crash reconciliation or merely serializing individual database transactions.

### S-08 — Frontend ephemeral port reservation is released before use

`_free_port()` binds port zero and closes the socket before returning; Next.js later binds the returned port ([`isolated_runtime.py:1160–1164`](../../services/repair-orchestrator/app/isolated_runtime.py#L1160-L1164), [`isolated_runtime.py:965–979`](../../services/repair-orchestrator/app/isolated_runtime.py#L965-L979)). Concurrent launches or unrelated local services can acquire it in the interval. This can cause readiness failure and intermittent connection to an unintended listener. Matching frontend/backend product data adds a useful readiness check but does not reserve ownership of the port.

No spontaneous collision was observed in this audit, and the eight-session load probe exercised backend UDS sessions rather than concurrent Next.js frontends. The project service's private `8765` port avoids this cross-session host-port race; both HTTP bridge implementations also retain their bound sockets.

**Mitigation:** retain/reserve the actual listener through launch where supported, or use a private frontend namespace/UDS. If Next.js cannot accept an inherited listener, detect bind failure and perform a bounded retry with a newly selected port. Test deliberate interposition by an audit-owned listener between selection and startup.

## Detailed assessment of controls that held

### Bubblewrap filesystem and namespace isolation

The base command explicitly requests `--unshare-all`, `--unshare-user`, `--die-with-parent`, `--new-session`, environment clearing, and dropping all capabilities. The explicit user namespace is a good safeguard because `--unshare-all` alone has conditional user-namespace semantics. The profile mounts `/usr`, available library directories, the selected Python distribution, site-packages, snapshot, and trusted launcher read-only. It supplies private `/proc` and `/dev` and remounts `/`, `/proc`, and `/dev` read-only.

Live observations: `/home` and `/sys` were absent; `/`, `/snapshot`, `/proc`, `/dev`, and `/dev/shm` were read-only. Writable `/tmp` was exactly 16 MiB and `/run` 1 MiB. A bounded attempt to write 20 MiB into `/tmp` failed with `ENOSPC` (`errno 28`). The project profile replaces `/tmp` with a 256 MiB tmpfs to hold its copied working tree. The apparently large filesystem capacity reported for read-only `/dev/shm` did not create a writable storage bypass.

The backend profile preflight checks host-versus-sandbox network and user namespace identities, tmpfs sizes, and read-only mounts. The project preflight checks fewer invariants (network namespace, root read-only, empty-snapshot environment-file exclusion). Extend it to assert the complete intended profile and approved mount sources, especially after fixing S-01.

No path out through `/proc/1/root`, a writable host mount, or a writable cgroup hierarchy was demonstrated. Snapshot creation rejects symlink paths and exports admitted application files; the project export bounds tracked files to 8 MiB each and 64 MiB total. These controls are valuable, but live dependency mounts sit outside that frozen identity. Path checks followed by ordinary opens/mounts are not atomic against a malicious same-UID host actor; protect owned directories and define that trust assumption rather than claiming they resist a fully compromised controller account.

**Residual kernel surface:** `CapEff` was zero and `NoNewPrivs` was `1`, but `Seccomp` was `0`. There is no Faultline syscall filter or explicit nested-user-namespace prohibition. Broad read-only `/usr` also supplies more executables and shared kernel entry points than a minimal runtime image. These are hardening gaps, not demonstrated escapes. Use a tested syscall allowlist, disable unnecessary namespace creation where supported, pin/update Bubblewrap and the host kernel, and consider a VM boundary for truly hostile workloads. Bubblewrap's security depends on its caller's profile; its user-namespace and capability controls do not create a separate kernel. [Bubblewrap implementation matching the tested version](https://github.com/containers/bubblewrap/blob/v0.12.0/bubblewrap.c).

### Cgroup v2 quotas and enforcement

The systemd user scope is established before command execution, and candidate subprocesses inherit membership. Manager-only environment variables are removed by `env -i` before Bubblewrap starts. Kernel files are read back for memory, swap, task count, CPU ratio, and group OOM behavior; unlimited or mismatched values fail closed. The launched process tree is compared with scope membership. Creating new sessions or PID namespaces does not itself remove processes from their inherited cgroup. Transient scope execution inherits the caller's environment, making the explicit clearing relevant. [systemd-run scope behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html).

The enforcement preflight deliberately allocates beyond a small probe scope and attempts more threads than its task limit. It requires scope-local memory OOM and pids-limit events, not merely a nonzero exit code. Observed preflight:

```json
{"memory_max_bytes":67108864,"memory_swap_max_bytes":0,"tasks_max":16,
 "allocation_attempt_bytes":268435456,"thread_attempts":64,
 "hog_exit_code":-9,"threads_started":13,"environment_clean":true,
 "oom_events":1,"oom_kill_events":1,"pids_max_events":1}
```

Existing live tests also passed the production 512 MiB allocation-kill and 64-task fork-hog checks. An additional four-child CPU probe observed throttled periods increasing by 13 under `cpu.max = 100000 100000`, confirming throttling on this host. The startup probe itself does not empirically test CPU scheduling; it verifies that configured ratio by readback.

The CPU quota is a rate, not a lifetime CPU-seconds budget. Memory limits include charged memory, not all resources in the host. These distinctions, parent hierarchy capacity, descriptor limits, evidence storage, and host helpers matter for exhaustion analysis. [Kernel cgroup v2 interfaces and accounting](https://docs.kernel.org/admin-guide/cgroup-v2.html).

`FAULTLINE_AGGREGATE_LIMITS=disabled` is an explicit fixture-runtime opt-out, not an automatic fallback. Its unverified status is recorded. Per-process rlimits cannot reproduce aggregate forked-process memory/CPU limits. Do not permit this mode in a hostile multi-tenant service. `ProjectRuntime` forces aggregate mode to `required`; unsupported configured project limits are rejected.

### Cleanup, signals, and temporary file ownership

`ManagedProcess.start()` shields process creation so cancellation does not simply lose a newly created child; it closes the liveness writer and awaits the launch result on error. Noninteractive stdout and stderr are independently drained and capped at 256 KiB each; overflow requests termination. Interactive browser stdout uses a separate protocol reader and a bounded stream limit. Systemd manager calls have timeouts and are reaped, though their output cap is checked after `communicate()` buffers it; the manager is a trusted source rather than a candidate-controlled stream.

Worker shutdown cancels active work and gives cleanup a separate budget. Embedded bridge servers deliberately leave process-wide signal handlers to the controller. Generation ownership is registered before launch, and fixture cleanup retains the generation if resource removal cannot be confirmed. Scope cleanup requests targeted kill/stop, resets failed units, and requires the manager to report absence. Failure leads to quarantine rather than a successful proof. These mechanisms materially reduce silent leaks and false verification.

Remaining availability edges deserve tests: repeated cancellation during shielded cleanup; an unresponsive manager; a pipe held by a detached host descendant; and teardown errors before socket/client closure. In particular, `_release_session()` closes backend handles only after `_stop_backend()` succeeds, and one-shot `backend_session()` ownership is local rather than registered in `generations` ([`isolated_runtime.py:1082–1105`](../../services/repair-orchestrator/app/isolated_runtime.py#L1082-L1105)). Preserve a durable recovery handle on unconfirmed cleanup while closing independently releasable local handles in `finally` blocks.

`TemporaryDirectory` gives unpredictable private directories for probes, while candidate writable storage is namespace-local tmpfs. Fixture generation runtime directories are created with mode 0700. Read-only exports and private tmpfs stop candidates from writing host evidence directly. Host browser profiles/evidence still need quota and retention controls (S-05); crash cleanup cannot rely solely on normal temporary-directory context exit.

### Network isolation and local transport

In the candidate namespace, a TCP connection to a controlled host-loopback listening port failed with `ConnectionRefusedError`; the namespace-local loopback had no connection to that host listener. The profile does not mount host resolver configuration or expose host interfaces, and does not request shared networking. The intentionally inherited UDS is the application communication capability. Project subprocess launch uses `close_fds=True`, keeping that listener in the trusted relay rather than the candidate command.

The host transport caps untrusted response bytes during streaming, rejects compressed bodies before expansion, sets timeouts, and does not follow redirects. The project bridge restricts `Host`, builds its backend URL with a fixed service authority, strips framing headers, and caps request bytes. These are good protections. They do not supply a host-network egress policy to the browser (S-02), or authenticate local callers (S-06). Project bridge body streaming also lacks the fixture bridge's explicit three-second whole-body timeout, so a slow local client can retain a request until broader session teardown.

### Concurrency and admission

Database `BEGIN IMMEDIATE` plus a singleton lease and one serial worker protect ordinary job admission. A CLI lock protects its installation's lifetime. Scopes and abstract sockets use UUID identities, candidate namespaces have private temporary filesystems, and project services can safely reuse port 8765. On this host, eight simultaneous backend sessions all returned healthy responses with verified quotas in 0.734 seconds; open controller descriptors were 7 before and 7 after cleanup. A separate batch of 32 managed host commands completed without a command failure in 0.185 seconds. These are bounded smoke measurements, not performance targets.

Scope verification repeatedly reads `/proc` and cgroup membership. Processes can fork or exit between those observations, so legitimate churn can produce a retry or infrastructure failure. Under machine-wide load, fixed three/five/ten-second readiness deadlines can also reject valid cold starts. This fails closed, but can make repairs flaky. Test this explicitly with churn and delayed managers, optimize membership observation if necessary, and report launch pressure separately from candidate defects. Avoid weakening the membership check to make a load test pass.

S-07 covers a gap beyond transactional admission: multiple startup owners. S-08 covers host frontend port reuse. Different installations can also concurrently allocate their individual quotas; no global resource admission bound was established by the eight-session probe.

### Cross-platform behavior and systems without Bubblewrap

| Environment | Observed or source-established behavior | Assurance limit |
| --- | --- | --- |
| Linux, working bwrap/user namespaces/systemd user manager/cgroup v2 | Real namespace, browser, quota, and cleanup tests passed | Applies to this host/profile |
| Linux, missing bwrap | `_sandbox`/backend preflight reject execution; no automatic host candidate fallback | Missing-tool paths covered by unit tests |
| Linux, bwrap installed but unusable | Actual profile launch must pass; binary existence alone is insufficient | Denied-userns host not separately provisioned |
| Linux, no usable cgroup v2/user manager | Required mode withholds readiness; explicit fixture opt-out remains distinguishable | Containers often expose binaries without delegation |
| Native macOS/Windows | CLI repair path checks `sys.platform` before loading Linux execution stack and reports unsupported sandbox repair | Native checks/demo capabilities do not establish candidate isolation |
| WSL2 | Documented as unverified; requires working systemd/cgroup/userns/browser profile | No WSL2 audit run |

Sources: [`cli_check.py:183–225`](../../services/repair-orchestrator/app/cli_check.py#L183-L225), [`isolated_runtime.py:853–875`](../../services/repair-orchestrator/app/isolated_runtime.py#L853-L875), and portability tests. Safe degradation is refusal of candidate execution while retaining non-executing/native checking features. Do not add an unsandboxed host execution fallback for convenience. A future alternative engine must establish equivalent isolation and expose its actual assurance level.

The Linux runtime uses `/proc`, `os.pipe2`, `pass_fds`, abstract sockets, fixed Python 3.13 paths, and systemd APIs. It is not itself portable merely because public CLI imports are guarded. Windows demo cleanup has a separate stop-file/process-tree implementation; Unix demo shutdown depends on the launcher trap. Both require native lifecycle testing. Twenty-three backend/root test skips on this host were PowerShell/Windows-specific, and no native-platform success is claimed.

## Verification record

All commands below ran against the audited execution source. Dependencies were installed from the lockfiles to enable real integration; installation/build products remained ignored. No application source was changed.

| Check | Result |
| --- | --- |
| `uv run --project services/repair-orchestrator --python 3.13 --locked pytest services/repair-orchestrator/tests` before browser/frontend setup | **999 passed, 9 skipped**, 50.68 s |
| Full orchestrator pytest after setup, with `FAULTLINE_REQUIRE_ISOLATED_TESTS=1` | **1008 passed**, 72.25 s; no skips or failures |
| Required live tests: `FAULTLINE_REQUIRE_ISOLATED_TESTS=1 uv run --project services/repair-orchestrator --python 3.13 --locked pytest services/repair-orchestrator/tests/test_isolated_runtime.py services/repair-orchestrator/tests/test_resource_limits_cgroup.py services/repair-orchestrator/tests/test_project_run.py` | **41 passed**, 20.83 s; no integration skips |
| Backend/root pytest after runner build | **324 passed, 23 skipped**, 12.57 s; skips require PowerShell/Windows |
| `make lint typecheck build` | Passed; Ruff checks/format passed, mypy passed for 38 backend and 56 orchestrator source files; both Python sdists and wheels built |
| `make provenance` | Fixture provenance and evaluation corpus verified: 10 holdout defects, 11 candidate patches |
| `npm --prefix apps/buggyshop-frontend run check` | Lint, typecheck, production build passed |
| `npm --prefix web/inspector-ui run check` | Typecheck and production build passed |
| `npm --prefix tools/browser-runner run check` | Typecheck/build passed; **132 tests passed**, 54.7 s |
| Synthetic dependency-prefix mount probe | Unexported marker visible: **confirmed S-01** |
| Actual project driver, loopback-only WebRTC probe | **3 STUN datagrams**, confirming S-02 |
| Host detached child / direct supervisor SIGTERM / grandchild reaping probes | Surviving child / four-second timeout / `Z` state, confirming S-04 |
| Namespaced detached descendant | Scope absence confirmed after stop/release |
| Same-installation second-runtime reconciliation | Active audit scope terminated, confirming runtime primitive in S-07 |
| Concurrent sessions / host managed processes | **8/8** quota-verified backend sessions; **32/32** host commands completed |

Initial verification failures were setup-related and are retained here for transparency: the first backend/root run had 3 failures because the browser runner was not yet built; a runner check initially could not collect tests because Inspector dependencies were missing. After those dependencies/builds completed, the corresponding checks above passed. No source workaround was introduced. Native browser UI suites and extended multi-host/platform soak tests were not part of the verification claimed here.

## Prioritized mitigation and acceptance plan

1. **Before hostile project execution:** remove project-derived interpreter mount authority (S-01), and enforce browser network isolation below Playwright (S-02). Acceptance: an excluded synthetic file stays invisible; forbidden host/LAN/Internet traffic generates zero listener hits, including WebRTC/UDP and IPv6.
2. **Strengthen browser/process boundaries:** require Chromium sandboxing everywhere (S-03); place helper trees in owned cgroups; handle supervisor signals and reap adopted descendants (S-04). Acceptance: detached grandchildren, early parent exit, direct supervisor SIGINT/SIGTERM, controller SIGKILL, and repeated cancellation leave no owned live tasks, unreaped children, or open inherited pipe writers.
3. **Bound total job impact:** add parent/job resource ceilings, helper sub-budgets, private quota-controlled browser/evidence storage, zero-core and descriptor limits (S-05). Acceptance: a synthetic hostile page cannot exceed the job's accounting budget or fill host storage; parallel installations retain controller headroom.
4. **Enforce owner and transport assumptions:** take a lifetime lock on API and CLI startup (S-07), authenticate or compartmentalize local IPC (S-06), and eliminate/retry frontend bind races (S-08). Acceptance: a second owner is rejected before reconciliation; an unauthorized local peer cannot alter a job; deliberate port interposition is classified and recovered safely.
5. **Expand required continuous validation:** current CI validates a deterministic HTTP service and sandbox prerequisites, but does not run the required live namespace/cgroup/browser suite ([`faultline-ci.yml`](../../.github/workflows/faultline-ci.yml)). Add a runner with known user-manager/cgroup delegation and run the required suite without skips. Include fork churn, cold browser starts, delayed manager responses, output floods, disconnected relays, temporary-storage exhaustion, restart ownership races, and repeated shutdown. Add actual Windows/macOS/WSL2 coverage only for the capabilities those platforms claim.

After these changes, re-audit the combined browser, bridge, supervisor, dependency image, and parent-cgroup boundary. Backend quota success alone is insufficient evidence for whole-job isolation.
