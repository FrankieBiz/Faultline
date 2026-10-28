# FaultLine Fixtures & Provenance

This directory contains deterministic test fixtures, seeded source files, and cryptographic provenance verification tools for the FaultLine platform.

---

## Directory Structure

* **`provenance.py`**: Cryptographic validator that checks SHA-256 hashes of test fixtures and source files against `manifest.json`. Guarantees reproducible evaluation without source tampering.
* **`manifest.json`**: Cryptographic hash manifest pinning exact file hashes and Git commits.
* **`seeds/`**: Seeded test scenarios including healthy baselines and seeded e-commerce checkout defects.
* **`evaluation/`**: Hash-pinned evaluation corpus. `holdout/` holds nine single-defect variants of the checkout route, each derived from the healthy seed; the registered seeded defect is referenced as a tenth case. `adversarial/` holds eleven candidate diffs for the seeded defect: two correct, six plausible but wrong, and three that the patch policy must reject. `cases.json` records each file's SHA-256 and the oracle failures measured when the case was authored. Verify with `python -m fixtures.evaluation.corpus` (part of `make provenance`); refresh hashes after deliberate authoring with `--write`. Corpus files are never imported by the controller; they execute only inside an isolated backend during evaluation. See [`docs/EVALUATION.md`](../docs/EVALUATION.md).
