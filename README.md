# Faultline

A project workspace for FrankieBiz's entry in the [Meta Global AI Developer Hackathon](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon), hosted by Meta and Cerebral Valley.

> **Project concept:** FaultLine reproduces a controlled checkout failure, asks a Meta model for a bounded source patch, and verifies restored behavior against protected browser and API tests. The approved design is [SpecV1](docs/SpecV1.md); application implementation and live validation remain to be completed.

## Start here

- [`docs/SpecV1.md`](docs/SpecV1.md) — approved implementation-ready specification for the controlled repair demo.
- [`docs/SpecV1-research-notes.md`](docs/SpecV1-research-notes.md) — primary-source research, design rationale, evidence limits, and review closure.
- [`AGENTS.md`](AGENTS.md) — instructions for every model and automation, including the immutable-source rule.
- [`docs/HACKATHON_BRIEF.md`](docs/HACKATHON_BRIEF.md) — event, judging, schedule, and resource facts with sources.
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — current project choices and account-specific details.
- [`meta-provided/`](meta-provided/) — original webinar screenshots. These files are read-only source artifacts; never modify them.

## Goal

Build a working, polished demo for the ten-day hackathon window and submit it by the official deadline. Optimize first for real-world impact (30% of the webinar judging rubric), then show thoughtful Meta AI tool use (25%), sound technical execution (20%), and a demo that works and is worth watching (25%).

## Source integrity

The webinar screenshots supplied by Frankie are preserved byte-for-byte in `meta-provided/webinar/` and checksummed in `meta-provided/SHA256SUMS`. Keep all interpretation and updates outside that directory. The event's public details can change; check the official page before relying on dates, rules, model access, or credits.
