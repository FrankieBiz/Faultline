# FaultLine Automation Scripts

Automation and orchestration scripts for the FaultLine platform.

---

## Scripts

* **`start-demo.sh`**: Launches the complete 4-tier stack (Storefront on 3000, Backend on 8000, Mission Control on 4000, Orchestrator on 9000) concurrently with clean termination handling.
* **`rehearse-demo.sh`**: Automated end-to-end rehearsal harness that runs the entire 180-second pitch scenario, reproducing the checkout crash, querying Meta's model, and verifying repair.
* **`reset.sh`**: Idempotent reset script that cleans temporary files, cancels orphaned worktrees, and restores clean state.
