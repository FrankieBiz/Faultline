"""Trusted runtime boundary and immutable execution evidence interfaces.

The repository does not yet contain the container profile or browser CLI. The
default boundary therefore blocks execution rather than running candidates on
the host. Integration supplies an implementation of Runtime only after those
components and their containment checks exist. Tests explicitly inject a
simulation; it cannot be selected through the HTTP API or environment.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.snapshots import Snapshot
from shared.contracts.models import ExecutionReport

Phase = Literal["baseline", "verification"]
REQUIRED_EVIDENCE = frozenset({"screenshot", "trace", "requests", "logs"})
REGRESSION_ASSERTIONS = frozenset(
    {
        "regression.missing_coupon",
        "regression.null_coupon",
        "regression.empty_coupon",
        "regression.whitespace_coupon",
        "regression.tenoff",
        "regression.fifteen",
        "regression.normalized_coupon",
        "regression.mixed_cart",
        "regression.mixed_cart_coupon",
        "regression.quantity_ten",
        "regression.empty_cart",
        "regression.duplicate_product",
        "regression.unknown_product",
        "regression.quantity_zero",
        "regression.quantity_eleven",
        "regression.quantity_negative",
        "regression.quantity_fraction",
        "regression.quantity_string",
        "regression.quantity_boolean",
        "regression.quantity_null",
        "regression.quantity_missing",
        "regression.unknown_coupon",
        "regression.invalid_coupon_type",
        "regression.client_price",
        "regression.unknown_fields",
        "regression.unknown_order",
        "regression.unknown_product_readback",
        "confirmation.checkout",
    }
)


@dataclass(frozen=True)
class RuntimeArtifact:
    """Bounded bytes returned only by the trusted runner, never the candidate."""

    role: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class RuntimeExecution:
    """Report and resource provenance observed by the runtime controller."""

    report: ExecutionReport
    generation_id: str
    snapshot_sha256: str
    exit_code: int
    artifacts: tuple[RuntimeArtifact, ...]


class RuntimeUnavailable(RuntimeError):
    """Required trusted runtime components or containment are unavailable."""


class CandidateRejected(RuntimeError):
    """Candidate compilation, readiness, or identity verification failed."""


class Runtime(Protocol):
    """Only an isolated runner implementation may execute candidate snapshots.

    Implementations persist/label resource intent with the supplied installation,
    job, and generation identities before creation. Methods must be cancellation
    safe; cleanup is idempotent and confirms removal rather than assuming it.
    """

    @property
    def ready(self) -> bool:
        """Whether the required runtime, oracle, and containment are ready."""
        ...

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        """Create an isolated baseline with an empty store and fresh browser."""
        ...

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        """Compile and start a fresh backend from the exact read-only snapshot."""
        ...

    async def execute(
        self,
        job_id: str,
        execution_id: str,
        phase: Phase,
        snapshot: Snapshot,
        timeout_ms: int,
    ) -> RuntimeExecution:
        """Run the fixed trusted suite once, returning bounded immutable evidence."""
        ...

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        """Confirm all resources owned by this installation/job are removed."""
        ...

    async def reconcile(self, installation_id: str) -> None:
        """Clean only this installation's leftovers before admitting jobs."""
        ...


class UnavailableRuntime:
    """Fail closed while the isolated runtime/browser runner is not configured."""

    @property
    def ready(self) -> bool:
        """Candidate execution remains unavailable by default."""
        return False

    async def prepare(self, installation_id: str, job_id: str, snapshot: Snapshot) -> None:
        """Reject a baseline that cannot use the required isolated runtime."""
        raise RuntimeUnavailable("isolated_runtime_unavailable")

    async def activate(self, job_id: str, snapshot: Snapshot) -> None:
        """Reject host execution of a candidate."""
        raise RuntimeUnavailable("isolated_runtime_unavailable")

    async def execute(
        self,
        job_id: str,
        execution_id: str,
        phase: Phase,
        snapshot: Snapshot,
        timeout_ms: int,
    ) -> RuntimeExecution:
        """Reject execution without the trusted oracle."""
        raise RuntimeUnavailable("trusted_runner_unavailable")

    async def cleanup(self, installation_id: str, job_id: str) -> None:
        """No resources can have been created by this implementation."""

    async def reconcile(self, installation_id: str) -> None:
        """No resources can have been created by this implementation."""
