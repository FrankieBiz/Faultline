"""Delta-debugging (ddmin) over the top-level keys of a JSON request payload.

A generic, tested library function. It is not part of repair jobs: a useful
minimization needs a real oracle that replays each subset against the failing
backend, and the controller does not yet capture or replay request bodies.
The result is only as meaningful as the oracle supplied by the caller.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Awaitable, Callable
from typing import Any

from shared.contracts.models import ContractModel


class MinimalIncidentPayload(ContractModel):
    """Immutable result of delta-debugging payload minimization."""

    original_payload: dict[str, Any]
    minimal_payload: dict[str, Any]
    removed_keys: list[str]
    reduction_ratio: float
    iterations: int
    duration_ms: float
    preserved_error_fingerprint: str


class DeltaDebugger:
    """Zeller's ddmin algorithm adapted for structured JSON incident payloads."""

    def __init__(self, max_iterations: int = 50) -> None:
        self.max_iterations = max_iterations

    async def minimize_async(
        self,
        payload: dict[str, Any],
        oracle: Callable[[dict[str, Any]], Awaitable[bool]],
        error_fingerprint: str,
    ) -> MinimalIncidentPayload:
        """Asynchronously find the 1-minimal dictionary that satisfies oracle."""
        started = time.monotonic()
        iterations = 0

        # Base case: verify the original payload reproduces
        iterations += 1
        if not await oracle(payload):
            return MinimalIncidentPayload(
                original_payload=payload,
                minimal_payload=payload,
                removed_keys=[],
                reduction_ratio=0.0,
                iterations=iterations,
                duration_ms=(time.monotonic() - started) * 1000,
                preserved_error_fingerprint=error_fingerprint,
            )

        current = copy.deepcopy(payload)
        keys = list(current.keys())

        # If 1 or 0 keys, already 1-minimal
        if len(keys) <= 1:
            return MinimalIncidentPayload(
                original_payload=payload,
                minimal_payload=current,
                removed_keys=[],
                reduction_ratio=0.0,
                iterations=iterations,
                duration_ms=(time.monotonic() - started) * 1000,
                preserved_error_fingerprint=error_fingerprint,
            )

        n = 2
        while len(keys) >= 2 and iterations < self.max_iterations:
            subsets = self._partition(keys, n)
            reduced = False

            # Check subsets
            for sub in subsets:
                iterations += 1
                candidate = {k: current[k] for k in sub}
                if await oracle(candidate):
                    current = candidate
                    keys = list(current.keys())
                    n = 2
                    reduced = True
                    break

            if reduced:
                continue

            # Check complements
            for sub in subsets:
                iterations += 1
                complement_keys = [k for k in keys if k not in sub]
                if not complement_keys:
                    continue
                candidate = {k: current[k] for k in complement_keys}
                if await oracle(candidate):
                    current = candidate
                    keys = list(current.keys())
                    n = max(n - 1, 2)
                    reduced = True
                    break

            if reduced:
                continue

            # If no subset or complement worked, increase granularity
            if n < len(keys):
                n = min(len(keys), n * 2)
            else:
                break

        # Secondary pass: minimize lists within the minimal dict (e.g. items list)
        for k, v in list(current.items()):
            if isinstance(v, list) and len(v) > 1:
                min_list = await self._minimize_list(current, k, oracle)
                current[k] = min_list

        removed = [k for k in payload if k not in current]
        orig_size = max(1, len(str(payload)))
        min_size = len(str(current))
        ratio = max(0.0, min(1.0, (orig_size - min_size) / orig_size))

        return MinimalIncidentPayload(
            original_payload=payload,
            minimal_payload=current,
            removed_keys=removed,
            reduction_ratio=round(ratio, 4),
            iterations=iterations,
            duration_ms=(time.monotonic() - started) * 1000,
            preserved_error_fingerprint=error_fingerprint,
        )

    def minimize_sync(
        self,
        payload: dict[str, Any],
        oracle: Callable[[dict[str, Any]], bool],
        error_fingerprint: str,
    ) -> MinimalIncidentPayload:
        """Synchronously find the 1-minimal dictionary that satisfies oracle."""
        import asyncio

        async def _wrap(p: dict[str, Any]) -> bool:
            return oracle(p)

        return asyncio.run(self.minimize_async(payload, _wrap, error_fingerprint))

    async def _minimize_list(
        self,
        base_payload: dict[str, Any],
        list_key: str,
        oracle: Callable[[dict[str, Any]], Awaitable[bool]],
    ) -> list[Any]:
        """Minimize items inside a list property while preserving failure."""
        items = list(base_payload[list_key])
        if len(items) <= 1:
            return items

        # Try single items
        for item in items:
            test_payload = copy.deepcopy(base_payload)
            test_payload[list_key] = [item]
            if await oracle(test_payload):
                return [item]

        # Try removing one item at a time
        idx = 0
        while idx < len(items) and len(items) > 1:
            candidate_list = items[:idx] + items[idx + 1 :]
            test_payload = copy.deepcopy(base_payload)
            test_payload[list_key] = candidate_list
            if await oracle(test_payload):
                items = candidate_list
            else:
                idx += 1

        return items

    @staticmethod
    def _partition(items: list[str], n: int) -> list[list[str]]:
        """Partition items into n roughly equal chunks."""
        n = max(1, min(n, len(items)))
        k, m = divmod(len(items), n)
        subsets = []
        for i in range(n):
            start = i * k + min(i, m)
            end = (i + 1) * k + min(i + 1, m)
            if start < end:
                subsets.append(items[start:end])
        return subsets
