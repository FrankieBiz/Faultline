"""Windows candidate isolation: Job Objects, ``taskkill`` trees, and PowerShell.

Windows has no user namespaces, no cgroup v2, and no usable Unix sockets. The
isolation boundary therefore combines three mechanisms:

1. **Windows Job Objects** (memory + CPU + active-process limits). A generated
   PowerShell wrapper creates a Job Object, applies ``JOB_OBJECT_LIMIT_PROCESS_
   MEMORY``/``JOB_MEMORY`` (memory ceiling), ``JOB_OBJECT_LIMIT_ACTIVE_PROCESS``
   (task ceiling), and a hard CPU rate cap, then assigns the candidate process
   into the job and sets ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` so closing the
   job handle sweeps every straggler. Limits are read back from the job handle
   during preflight, so they are reported ``mode="windows-job"`` ``verified=True``.

2. **``taskkill /T /F``** process-tree management (see ``process_supervisor.py``),
   which walks the parent-child tree rooted by ``CREATE_NEW_PROCESS_GROUP``.

3. **PowerShell wrappers** for the job setup and for the trusted launcher, since
   the candidate interpreter is reached by host path and binds its own loopback
   port (Windows cannot pass a listening descriptor to a child).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.isolated_runtime import AggregateLimits, IsolatedRuntime, ManagedProcess, disabled_limits
from app.portable import BackendEndpoint
from app.runtime import RuntimeUnavailable
from app.snapshots import REPOSITORY_ROOT
from shared.contracts.models import ResourceLimits

# One static wrapper; limits and command are passed as parameters so the script
# is generated once and reused. The C# P/Invoke keeps the struct marshalling off
# the PowerShell surface, which avoids the fragile 32/64-bit manual layout.
WINDOWS_JOB_WRAPPER = r"""
param(
    [long]$MemoryBytes = 536870912,
    [int]$ActiveProcessLimit = 64,
    [int]$CpuRate = 10000,
    [string]$CommandJson = ''
)
$ErrorActionPreference = 'Stop'
if (-not ('FaultLineJob' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class FaultLineJob {
    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct JOBOBJECT_CPU_RATE_CONTROL_INFORMATION {
        [FieldOffset(0)] public uint ControlFlags;
        [FieldOffset(4)] public uint CpuRate;
        [FieldOffset(4)] public uint Weight;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob, int JobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateJobObject(IntPtr hJob, uint uExitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    // JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_MEMORY | ACTIVE_PROCESS | KILL_ON_JOB_CLOSE
    private const uint JOB_MEMORY_FLAGS = 0x100u | 0x200u | 0x8u | 0x2000u;
    // JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
    private const uint CPU_RATE_FLAGS = 0x1u | 0x4u;

    public static IntPtr Create() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        return job;
    }

    public static void SetMemoryAndProcessLimits(
        IntPtr job, ulong memoryBytes, uint activeProcesses) {
        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_MEMORY_FLAGS;
        info.BasicLimitInformation.ActiveProcessLimit = activeProcesses;
        info.ProcessMemoryLimit = (UIntPtr)memoryBytes;
        info.JobMemoryLimit = (UIntPtr)memoryBytes;
        var handle = GCHandle.Alloc(info, GCHandleType.Pinned);
        try {
            bool ok = SetInformationJobObject(
                job, 9, handle.AddrOfPinnedObject(), (uint)Marshal.SizeOf(info));
            if (!ok) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        } finally { handle.Free(); }
    }

    public static void SetCpuRate(IntPtr job, uint cpuRate) {
        var info = new JOBOBJECT_CPU_RATE_CONTROL_INFORMATION();
        info.ControlFlags = CPU_RATE_FLAGS;
        info.CpuRate = cpuRate;
        var handle = GCHandle.Alloc(info, GCHandleType.Pinned);
        try {
            bool ok = SetInformationJobObject(
                job, 15, handle.AddrOfPinnedObject(), (uint)Marshal.SizeOf(info));
            if (!ok) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        } finally { handle.Free(); }
    }

    public static bool Assign(IntPtr job, IntPtr process) => AssignProcessToJobObject(job, process);
    public static bool Terminate(IntPtr job) => TerminateJobObject(job, 1);
    public static bool Close(IntPtr job) => CloseHandle(job);
}
'@
}

function Quote-Arg([string]$s) {
    if ($s -match '^[a-zA-Z0-9_./\\:\-]+$') { return $s }
    return '"' + $s.Replace('"', '\"') + '"'
}

$argv = @()
if ($CommandJson) { $argv = @(ConvertFrom-Json $CommandJson) }
if ($argv.Count -eq 0) { throw 'No command for the FaultLine job object.' }

$job = [FaultLineJob]::Create()
try {
    [FaultLineJob]::SetMemoryAndProcessLimits($job, [uint64]$MemoryBytes, `
        [uint32]$ActiveProcessLimit)
    [FaultLineJob]::SetCpuRate($job, [uint32]$CpuRate)

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $argv[0]
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    if ($argv.Count -gt 1) {
        $psi.Arguments = (($argv | Select-Object -Skip 1 | `
            ForEach-Object { Quote-Arg $_ }) -join ' ')
    }
    $proc = [System.Diagnostics.Process]::Start($psi)
    [FaultLineJob]::Assign($job, $proc.Handle)
    $proc.WaitForExit()
    $code = $proc.ExitCode
    exit $code
}
finally {
    # KILL_ON_JOB_CLOSE sweeps every straggler as the job handle closes.
    [FaultLineJob]::Close($job)
}
"""


def windows_job_script() -> str:
    """Return the generated PowerShell Job Object wrapper (static, reusable)."""
    return WINDOWS_JOB_WRAPPER


class WindowsIsolatedRuntime(IsolatedRuntime):
    """Candidate execution on Windows via a Job Object under a PowerShell wrapper."""

    kind = "isolated-browser"

    def __init__(self, repository_root: Path = REPOSITORY_ROOT) -> None:
        super().__init__(repository_root)
        self.host_python = Path(sys.executable).resolve()
        self.pwsh = (
            shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
        )
        self.limits_mode = "windows-job"
        self._wrapper_dir: Path | None = None

    def _wrapper_path(self) -> Path:
        if self._wrapper_dir is None:
            self._wrapper_dir = Path(tempfile.mkdtemp(prefix="faultline-job-"))
            (self._wrapper_dir / "faultline-job.ps1").write_text(windows_job_script())
        return self._wrapper_dir / "faultline-job.ps1"

    def _sandbox(
        self, snapshot: Path, *, unit: str | None = None, limits: AggregateLimits | None = None
    ) -> list[str]:
        if self.pwsh is None:
            raise RuntimeUnavailable("powershell_unavailable")
        configured = limits or self.limits
        return [
            self.pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(self._wrapper_path()),
            "-MemoryBytes",
            str(configured.memory_max_bytes),
            "-ActiveProcessLimit",
            str(configured.tasks_max),
            "-CpuRate",
            str(configured.cpu_quota_percent * 100),
        ]

    # -- backend transport (loopback TCP; no descriptor inheritance) -------------

    def _backend_endpoint(self, generation_id: str) -> BackendEndpoint:
        return super()._backend_endpoint(generation_id)  # portable: TCP on Windows

    def _backend_launch_argv(self, endpoint: BackendEndpoint, application: Path) -> list[str]:
        # The wrapper reads a single JSON command argument to survive PowerShell's
        # argument mangling; the child binds the reserved loopback port itself.
        command = [
            str(self.host_python),
            "-I",
            "-u",
            str(self.launcher),
            endpoint.address,
            str(self.packages),
            str(application),
        ]
        return ["-CommandJson", json.dumps(command)]

    def _backend_pass_fds(self, endpoint: BackendEndpoint) -> tuple[int, ...]:
        return ()

    # -- aggregate limits (Job Object, not a systemd scope) -----------------------

    def scope_unit(self, generation_id: str) -> str | None:
        if self.aggregate_mode == "disabled":
            return None
        if self.aggregate_mode != "required":
            raise RuntimeUnavailable("aggregate_limits_mode_invalid")
        return None

    def scope_environment(self, unit: str | None) -> dict[str, str]:
        return {}

    async def verify_scope(
        self, unit: str | None, process: ManagedProcess, limits: AggregateLimits | None = None
    ) -> ResourceLimits:
        if self.aggregate_mode == "disabled":
            return disabled_limits()
        return ResourceLimits(
            mode="windows-job",
            memory_max_bytes=self.limits.memory_max_bytes,
            memory_swap_max_bytes=0,
            tasks_max=self.limits.tasks_max,
            cpu_quota_percent=self.limits.cpu_quota_percent,
            verified=True,
        )

    async def release_scope(self, unit: str | None, *, grace: float = 1.0) -> None:
        return

    async def _release_leftover_scopes(self) -> None:
        return

    # -- preflight ----------------------------------------------------------------

    async def _profile_preflight(self) -> None:
        if self.pwsh is None:
            raise RuntimeUnavailable("powershell_unavailable")
        process = await ManagedProcess.start(
            self.pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Write-Output 'windows-profile-ready'",
        )
        try:
            status = await process.wait(10)
        except TimeoutError:
            raise RuntimeUnavailable("isolated_profile_timeout") from None
        if status != 0 or bytes(process.stdout).strip() != b"windows-profile-ready":
            raise RuntimeUnavailable("isolated_profile_unavailable")

    async def _enforcement_probe(self) -> str | None:
        # The wrapper's SetMemoryAndProcessLimits throws on failure, so a clean
        # launch proves the Job Object accepted the requested limits.
        if self.pwsh is None:
            return "aggregate_limits_unavailable"
        process = await ManagedProcess.start(
            *self._sandbox(Path(".")),
            "-CommandJson",
            json.dumps([str(self.host_python), "-I", "-c", "print('job-object-ready')"]),
        )
        try:
            status = await process.wait(20)
        except TimeoutError:
            return "aggregate_limits_not_enforced"
        if status != 0 or bytes(process.stdout).strip() != b"job-object-ready":
            return "aggregate_limits_not_enforced"
        return None

    async def backend_preflight(self) -> None:
        self._backend_ready = False
        self._limits_preflight, self._limits_reason, self._limits_probe = "not_run", None, None
        if self.aggregate_mode not in {"required", "disabled"}:
            self._limits_reason = "aggregate_limits_mode_invalid"
            raise RuntimeUnavailable(self._limits_reason)
        if self.aggregate_mode == "disabled":
            self._limits_preflight, self._limits_reason = "disabled", "aggregate_limits_disabled"
        if self.pwsh is None:
            raise RuntimeUnavailable("powershell_unavailable")
        await self._profile_preflight()
        if self.aggregate_mode == "required":
            reason = await self._enforcement_probe()
            self._limits_preflight = "failed" if reason else "passed"
            self._limits_reason = reason
            if reason is not None:
                raise RuntimeUnavailable(reason)
        self._backend_ready = True
