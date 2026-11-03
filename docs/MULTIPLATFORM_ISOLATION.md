# FaultLine multiplatform isolation: audit, design, and adapters

**Status:** Implemented. The Linux engine is unchanged in behavior; the macOS
(`sandbox-exec` + `setrlimit` + Docker fallback) and Windows (Job Objects +
`taskkill` + PowerShell) engines are new and select automatically.

FaultLine's candidate-execution isolation previously ran **only on Linux**: it
hard-coded `bubblewrap` (bwrap), a transient `systemd-run` user scope, and
cgroup v2 in `services/repair-orchestrator/app/isolated_runtime.py`. This
document records the POSIX-only assumptions found, the platform seam that
replaces them, and the concrete adapters for each host.

---

## 1. Audit findings

The following POSIX/Linux-only assumptions were found. Each is now addressed.

| # | Assumption | Where | Impact | Resolution |
| --- | --- | --- | --- | --- |
| A1 | `os.pipe2(os.O_CLOEXEC)` for the liveness pipe | `isolated_runtime.py` `ManagedProcess.start` | `os.pipe2` does not exist on macOS or Windows | `app/portable.py::portable_pipe` (`os.pipe` + `set_inheritable`) |
| A2 | Abstract `\0`-prefixed Unix sockets for the candidate backend | `isolated_runtime.py` `_launch_backend` | Abstract namespace is Linux-only; Windows has no `AF_UNIX` | `app/portable.py::backend_endpoint` (abstract Unix / named Unix / loopback TCP) |
| A3 | `os.killpg` + `start_new_session` process-group teardown | `process_supervisor.py` | `killpg` is POSIX-only; no process groups on Windows | Windows branch: `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F` |
| A4 | `pass_fds` descriptor inheritance to the backend | `isolated_runtime.py`, `process_supervisor.py` | Windows cannot pass listening descriptors | Windows uses a loopback port the child binds itself; stop-file liveness |
| A5 | `systemd-run`/`systemctl` scope discovery and cgroup v2 files under `/sys/fs/cgroup` | `isolated_runtime.py` (`CGROUP_ROOT`, `scope_unit`, `verify_scope`, `release_scope`, `_release_leftover_scopes`, `_enforcement_probe`) | Does not exist on macOS/Windows | Encapsulated as the Linux aggregate-limit lifecycle; other hosts override it |
| A6 | `bwrap` argv and `/proc/self/ns/{net,user}` namespace preflight | `isolated_runtime.py::_sandbox`, `_profile_preflight` | `/proc/…/ns` is Linux-only | `_sandbox`/`_profile_preflight` become per-host |
| A7 | Hard-coded namespace paths `/python`, `/packages`, `/snapshot`, `/trusted_backend.py` | `isolated_runtime.py`, `isolated_backend.py` | These mounts only exist inside bwrap | `isolated_backend.py` now takes optional package/application paths; non-Linux passes host paths |
| A8 | `resource.setrlimit` in the launcher | `isolated_backend.py` | `RLIMIT_AS`/`RLIMIT_NPROC` unavailable on Windows | `_apply_rlimits()` no-ops on Windows |
| A9 | `bubblewrap_unavailable` gate in preflight | `isolated_runtime.py::backend_preflight` | Blocks macOS/Windows entirely | Each host's `backend_preflight` checks its own binaries |
| A10 | `ResourceLimits.mode` only `cgroup-v2-scope`/`disabled` | `shared/contracts/models.py` | Cannot record macOS/Windows limits honestly | New modes `rlimits`, `windows-job`, `docker` |
| A11 | Proof/verifier hard-code `cgroup-v2-scope` | `proof_bundle.py`, `tools/verify_bundle.py` | macOS/Windows verified repairs could not produce valid proof bundles | Both now accept any *verified* mode |

Also audited but left intentionally unchanged (documented below):
- `project_runtime.py` / `project_launcher.py` (project-mode `faultline run`)
  still require Linux bwrap. Project mode is the arbitrary-repository path and
  uses the strongest boundary; Docker is the documented fallback for macOS.
- `cli_check.sandbox_readiness` and the `doctor` wording still say "sandbox
  repair requires Linux" for the *project* path, which remains accurate.

---

## 2. Platform seam

`IsolatedRuntime` (Linux) now exposes a small set of overridable methods that
the macOS and Windows engines replace. Linux returns the same argv and
behavior as before.

| Seam | Linux (unchanged) | macOS | Windows |
| --- | --- | --- | --- |
| `_sandbox(snapshot, unit, limits)` | `bwrap …` prefix | `sandbox-exec -f profile.sb` (or `docker run …`) | `pwsh -File faultline-job.ps1 …` |
| `_backend_endpoint(generation_id)` | abstract Unix socket | named Unix socket (`flt-<id>.sock`) | loopback TCP port |
| `_backend_launch_argv(endpoint, app)` | `/python/bin/python3.13 … /trusted_backend.py <fd>` | host `python … launcher <fd> <pkgs> <app>` | host `python … launcher <port> <pkgs> <app>` (as JSON) |
| `_backend_pass_fds(endpoint)` | `(fd,)` | `(fd,)` | `()` |
| `_backend_client(endpoint)` | `BoundedUDSTransport` | `BoundedUDSTransport` (named) | `BoundedTCPTransport` |
| `scope_unit` / `scope_environment` | systemd `--unit=` scope + manager env | `None` / `{}` | `None` / `{}` |
| `verify_scope` | read cgroup v2 files, `verified=True` | `rlimits` record, `verified=False` | `windows-job` record, `verified=True` |
| `release_scope` / `_release_leftover_scopes` | `systemctl kill/stop`, list scopes | no-op | no-op |
| `backend_preflight` / `_profile_preflight` / `_enforcement_probe` | bwrap namespace + cgroup probe | sandbox-exec deny probe + rlimit probe | PowerShell probe + Job Object probe |

`app/isolation/select_runtime(repository_root)` picks the engine from
`app.portable.current_host()`. `main.py` now calls it instead of importing
`IsolatedRuntime` directly.

---

## 3. Per-host design

### 3.1 Linux — unchanged

bwrap user/namespace isolation plus a transient systemd user scope whose cgroup
v2 limits are read back and whose enforcement is probed before readiness. This
is the existing, already-tested engine.

### 3.2 macOS — `sandbox-exec` + `setrlimit`, Docker fallback

- **Filesystem/network isolation:** a deny-by-default SealedBSD profile generated
  by `isolation/darwin.py::sandbox_profile`. Read access is limited to the
  interpreter, its packages, the snapshot, the launcher, and system library
  directories; writes are allowed only under `/tmp`; the network is loopback-only.
- **Resource limits:** per-process `setrlimit` (memory, file descriptors,
  processes, CPU time) applied by `isolated_backend.py` before any candidate
  import. There is no cgroup, so this is per-process rather than aggregate and
  is recorded honestly as `mode="rlimits"` with `verified=False`.
- **Transport:** named Unix socket under a private temp directory (macOS has no
  abstract namespace).
- **Fallback:** when `sandbox-exec` is absent (it is deprecated on Apple
  Silicon), `_sandbox` emits `docker run --read-only --network bridge
  --publish 127.0.0.1:P:P --memory … --pids-limit … --cpus … <image>`, and the
  limits are read back from the container's cgroup, reported `mode="docker"`
  with `verified=True`. The image must already contain the candidate Python
  runtime; `FAULTLINE_RUNTIME_IMAGE`-style pinning is documented in the module.

### 3.3 Windows — Job Objects + `taskkill` + PowerShell

- **Resource limits:** `isolation/windows.py` generates a PowerShell wrapper that
  P/Invokes `kernel32` to create a Job Object and set
  `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (process/job memory + active-process
  limit) and `JOBOBJECT_CPU_RATE_CONTROL_INFORMATION` (hard CPU rate cap), with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so closing the handle sweeps stragglers.
  Reported `mode="windows-job"`, `verified=True`.
- **Process tree:** `process_supervisor.py` launches with
  `CREATE_NEW_PROCESS_GROUP` and tears the tree down with `taskkill /T /F`;
  the controller signals shutdown via a stop-file (Windows cannot pass the
  liveness pipe descriptor).
- **Transport:** loopback TCP — the child binds the reserved port itself.
- **Trusted launcher:** the command is passed to the wrapper as a single JSON
  argument to survive PowerShell's argument mangling.

---

## 4. `ResourceLimits` modes

`shared/contracts/models.py` now accepts five modes, each with an honest
validator:

| mode | memory | swap | tasks | cpu | verified |
| --- | --- | --- | --- | --- | --- |
| `cgroup-v2-scope` | required | required | required | required | read back from kernel |
| `rlimits` | required | `None` | required | `None` | `False` (macOS cannot read back) |
| `windows-job` | required | optional | required | optional | read back from the job handle |
| `docker` | required | optional | required | optional | read back from the container cgroup |
| `disabled` | `None` | `None` | `None` | `None` | `False` |

`proof_bundle.py` and `tools/verify_bundle.py` now treat *any* verified mode as
`recorded-isolated`, so a macOS Docker or Windows Job Object repair produces a
valid proof bundle.

---

## 5. Verification

Run in this repository (Linux CI):

```bash
uv run --project services/repair-orchestrator --python 3.13 --locked --no-env-file \
  pytest services/repair-orchestrator/tests
```

- **1156 passed, 9 skipped** (skips are environment-only: browser runner not
  built, bwrap/systemd unavailable). The single failure
  `test_project_browser_webrtc_cannot_send_stun_udp` is pre-existing and needs
  `make runner`; it is unrelated to isolation.
- `ruff check` and `ruff format --check` clean; `mypy` clean (62 files).
- `tools/verify_bundle.py` and `scripts/export_replay.py` tests pass.
- New `tests/test_isolation_adapters.py` covers host selection, portable pipe,
  per-host endpoint kinds, the sandbox-exec profile, the Job Object wrapper,
  per-host argv generation, and the new `ResourceLimits` modes. The macOS and
  Windows *enforcement* paths must be exercised on their own hosts (this is
  inherent: cgroup/sandbox-exec/Job Object mechanisms do not exist on Linux).

---

## 6. Known limitations / follow-ups

- **Project mode (`faultline run`)** still requires Linux bwrap; macOS uses
  Docker (documented) and Windows is not yet wired for arbitrary repositories.
- **macOS `rlimits` is per-process**, not aggregate across a tree; the Docker
  fallback is the verified aggregate path.
- **Windows filesystem/network isolation** is weaker than Linux: the Job Object
  bounds resources but does not namespace the filesystem or network. The trusted
  launcher and read-only mounts remain the boundary, and this is stated in the
  `ResourceLimits` record rather than overstated.
- `cli_check.sandbox_readiness`/`doctor` wording still targets the project path
  and should be updated if project-mode macOS/Windows support lands.
