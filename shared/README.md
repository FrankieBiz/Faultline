# FaultLine Shared Contracts & Configuration

This directory contains the central data contracts and scenario definitions shared across the BuggyShop backend, the browser runner, and the repair orchestrator.

---

## Directory Structure

* **`contracts/models.py`**: Canonical Pydantic v2 data models for execution evidence, job states, repair proposals, and telemetry events. Configured with `extra="forbid"`, strict typing, and UTC timestamp enforcement.
* **`config/scenarios.py`**: Ground-truth scenario definitions, expected assertions, and defect fingerprints used to deterministically verify whether a test failure matches known criteria.
