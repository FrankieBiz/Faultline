# FaultLine Fixtures & Provenance

This directory contains deterministic test fixtures, seeded source files, and cryptographic provenance verification tools for the FaultLine platform.

---

## Directory Structure

* **`provenance.py`**: Cryptographic validator that checks SHA-256 hashes of test fixtures and source files against `manifest.json`. Guarantees reproducible evaluation without source tampering.
* **`manifest.json`**: Cryptographic hash manifest pinning exact file hashes and Git commits.
* **`seeds/`**: Seeded test scenarios including healthy baselines and seeded e-commerce checkout defects.
