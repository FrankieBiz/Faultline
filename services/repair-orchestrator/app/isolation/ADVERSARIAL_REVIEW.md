# Candidate isolation: adversarial lifecycle review

## Findings addressed

| Attack or failure | Previous behavior | Hardened behavior |
| --- | --- | --- |
| Windows candidate immediately spawns children | Candidate ran before Job Object assignment; failed assignment was ignored | Start suspended, check assignment, then resume; descendants inherit a job without breakaway flags |
| Windows assignment/resume failure | Candidate/process handle could survive setup failure | Terminate the candidate and job; bound the termination wait; close both native process and thread handles in `finally` |
| Windows limits differ from requested values | Successful setters were treated as readback | Query memory, process-count, kill-on-close flags, and CPU limits before launch; mismatch fails closed |
| Windows wrapper exits abnormally | Child status could be obscured by cleanup output | Preserve the child exit code and suppress the boolean result of closing the job handle |
| Windows `taskkill` hangs, fails, or is unavailable | Unbounded subprocess call; no checked fallback | Two-second timeout; force-kill the wrapper on failure, causing its Job Object handle to close |
| Stop times out before Windows supervisor observes request | Controller deleted the stop file in `finally` | Keep the stop request until the supervisor has actually exited; a later stop can retry cleanup |
| POSIX child exits between poll and SIGTERM | `ProcessLookupError` bypassed final sweep/wait | Tolerate the race, still attempt group SIGKILL and reap the direct child |
| Darwin candidate forks and daemonizes | Broad `process*` permission permitted descendants to escape process-group ownership | Permit exec for the trusted launch, explicitly deny fork; native candidate execution is a single process |
| Snapshot path contains profile syntax | Raw path interpolation could inject Seatbelt expressions | Escape quotes, backslashes, and control characters in profile strings |
| Darwin memory probe | Allocated indefinitely without applying launcher limits | Apply the launcher's actual hard rlimits first; cap the allocation loop and reject a missing `MemoryError` |
| Darwin profile preflight | Generated `;try:` was invalid Python, so the native smoke probe could never pass | Generate valid statements and compile the probe in the regression test |
| Custom Windows probe limits | Reporting returned production defaults | Report the supplied memory, process, and CPU configuration |

## SIGTERM, SIGKILL, threads, and reaping

The POSIX supervisor owns a separate candidate session/process group. Liveness
pipe EOF triggers group SIGTERM, allows one second of grace, then sends group
SIGKILL even if the leader already exited. `Popen.wait()` reaps the direct
child, and the controller awaits the supervisor and output pumps. Daemon
threads share their process's lifetime; they do not survive process death.
The tests exercise real ignored SIGTERM, SIGKILL status translation, abnormal
exits, sixteen concurrent exits, and direct-child zombie reaping. Mocked
supervisor tests verify the group sweep after leader exit and the exit race.

A process in uninterruptible kernel sleep may not exit promptly even after
SIGKILL. The controller's four-second stop deadline raises `TimeoutError`;
it does **not** prove the process tree was reaped. The POSIX supervisor remains
the direct child's waiter until the kernel allows exit. Rlimits are kernel
state attached to a process, not handles to close: they persist with the task
until it exits. They do not impose a wall-clock deadline on kernel I/O.

On Windows, `taskkill /T /F` and the fallback `Popen.kill()` use forced process
termination rather than POSIX signal delivery. Closing the wrapper's last
non-inheritable Job Object handle invokes kill-on-close for assigned processes,
including grandchildren. Setup failure and normal exit explicitly terminate
the job. Native process/thread handles close even if the five-second child
termination wait fails. Kernel cleanup can still be delayed; closing a handle
is not confirmation that all I/O and descendant termination completed.

## Remaining architecture limits

- **Windows Jobs are resource containment, not a hostile-code security
  sandbox.** The candidate still has the host user's filesystem/network rights.
  A restricted token/AppContainer or VM boundary is required for that threat
  model. Limit readback alone must not be presented as proof of those rights.
- **Windows controller crashes are not detected by stop files.** Explicit stop
  and cancellation are covered. A controller killed before writing the stop
  request can leave its supervisor and wrapper running. The job closes when its
  wrapper dies, not merely when the controller dies. An inherited controller
  process handle or an outer service-owned job is still needed.
- **Suspended creation still has a wrapper-crash window.** If the wrapper is
  forcibly killed between `CreateProcessW` and checked job assignment, a
  suspended, unassigned process can survive. Atomic assignment through
  `PROC_THREAD_ATTRIBUTE_JOB_LIST` is the follow-up for supported Windows hosts.
- **Native Darwin limits are not aggregate memory/CPU-rate enforcement.**
  `RLIMIT_NPROC` is UID-scoped rather than a dedicated candidate task budget;
  thread accounting and address-space enforcement are host-dependent. Native
  mode remains `verified=False`; failure of the memory probe prevents readiness.
  Fork denial intentionally excludes candidate applications needing subprocesses.
- **Generic POSIX supervision is not a subreaper.** It reaps its direct child;
  orphan grandchildren rely on an outer PID namespace/init. `killpg` cannot
  reach a process that changes session/group. Native Darwin blocks candidate
  forks; trusted browser subprocesses still need their existing outer boundary.
- **Darwin policy is broader than a per-candidate capability boundary.** Shared
  `/tmp` writes, loopback network access, and broad system read paths remain.
  These are not equivalent to Linux's mount/network namespaces.
  The profile smoke probe's `/etc/hosts` write can also fail from ordinary user
  permissions, so it is not independent proof of Seatbelt enforcement.
- **Docker fallback cleanup is not established by killing the Docker CLI.**
  `--rm` only removes a container after it exits; there is no retained container
  identity for forced removal or per-launch limit readback in this adapter.

## Validation scope

The adapter suite uses real POSIX subprocesses and platform mocks on Linux.
Windows-only tests run the generated wrapper against real memory/process limits
and abnormal exit status when executed on Windows. Linux mocks and source
contracts cannot validate Seatbelt syntax, Windows P/Invoke ABI, enforcement,
or forced wrapper death. PowerShell parsing/C# compilation can be checked on
Linux separately, but successful compilation is not native execution evidence.

References: [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[checked job assignment](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject),
[suspended-create crash window](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812),
and [POSIX child waiting](https://man7.org/linux/man-pages/man2/waitpid.2.html).
