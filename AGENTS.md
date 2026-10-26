# Faultline agent instructions

## Project mission

This repository supports FrankieBiz's entry in Meta's Global AI Developer Hackathon. Read `README.md`, then `docs/HACKATHON_BRIEF.md` and `docs/PROJECT_STATUS.md` before planning or changing project work.

## Protected Meta-provided materials

**Never edit, rename, replace, reformat, optimize, or delete anything inside `meta-provided/`.** Treat every file there as an immutable source artifact supplied by Meta/Cerebral Valley or captured from their official event materials. Read it for context, but put summaries, interpretations, corrections, and derived notes in `docs/` or elsewhere outside `meta-provided/`. If a protected source appears inconsistent with a newer official source, preserve it and document the discrepancy separately with citations and dates.

This is a project-level instruction for every model and automation working in this repository. Do not treat a request to update project docs as permission to alter the protected source directory. Changes to protected source files require Frankie to make them directly.

`meta-provided/SHA256SUMS` records the original webinar image hashes. Check hashes if source integrity is in question.

## Source precedence

1. Current official hackathon rules and official event pages for requirements and deadlines.
2. Original webinar artifacts in `meta-provided/` for information presented in the webinar.
3. Frankie-provided account details for personal access, credits, and preferences.
4. Derived summaries in `docs/`, which may be updated when sources change.

Cite the source and retrieval date when adding time-sensitive facts. Mark unverified personal account details as unverified; never infer that an event-wide tool or partner offer is enabled on Frankie's account.

## Git identity

When creating commits, use FrankieBiz's GitHub identity: `Francis Bisignano <frankabisignano@gmail.com>`. Never author or commit as Codex, OpenAI, ChatGPT, or an AI agent. Do not change the global Git identity; set repository-local identity if needed.

## Secrets

Never commit API keys, access tokens, passwords, or private credentials. Use ignored local environment files and document required variable names without values.
