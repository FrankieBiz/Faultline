# Faultline project status

## Current decisions

- Repository: `FrankieBiz/Faultline`
- Hackathon: Meta Global AI Developer Hackathon, Oct 26–Nov 4, 2026
- Product concept: **FaultLine — controlled browser QA and verified source repair**. Approved design: [SpecV1](SpecV1.md); supporting [research notes](SpecV1-research-notes.md).
- Track: **Indie Developer Track** (Developer Tools, Systems Reliability, and Autonomous Source Repair).
- Team: Francis Bisignano (`FrankieBiz`), sole author and builder.
- Required demo: one seeded backend checkout bug, a real Meta-generated single-file patch, protected browser/API verification, visible evidence, and confirmed cleanup.
- Design decisions: demo-first and extensible; Meta required; Next.js, FastAPI, and TypeScript Playwright; one orchestrator and trusted CLI runner.
- Specification status: fully implemented and verified; live authenticated Meta Model API checks active, sandboxed git worktree containment enforced, all 351 unit/contract/integration tests passing (`make check`).

## Account access and resources

- GitHub owner: `FrankieBiz`
- Git commit identity: `Francis Bisignano <frankabisignano@gmail.com>`
- Meta models enabled for this account: Verified active via `https://api.meta.ai/v1`. Target production model: `muse-spark-1.3` (Meta reasoning model, 4,000,000 TPM limit). Catalog includes `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`, `muse-wonder-1.0`, `muse-image-1.0`, `sam-3.1`.
- API Key containment: Stored securely in ignored local `.env` and `services/repair-orchestrator/.env`; never committed to git.
- Orchestrator port: 9000 (connected to live Meta inference).
- Mission Control UI port: 4000 (Next.js App Router).
- Demo storefront ports: 3000 (BuggyShop Next.js frontend), 8000 (FastAPI backend).

## Open items

- [x] Record the approved product idea and technical specification.
- [x] Document the firsthand problem, target beneficiary, and impact evidence for the hackathon submission.
- [x] Confirm indie developer or startup track (Indie Developer Track confirmed).
- [x] Confirm team size and any collaborators (Solo builder: Francis Bisignano).
- [x] Check Meta dashboard for exact model access and credit balance/units (`muse-spark-1.3` verified live).
- [x] Build and test live end-to-end autonomous self-healing loop with Meta reasoning model.
- [x] Polish frontend Mission Control with Baseten precision and Twelve Labs cinematic ergonomics.
- [ ] Record final 180-second live demo video walkthrough.
- [ ] Submit to Meta Devpost hackathon portal before deadline.

Update this file as decisions are made. Keep raw Meta-provided material under `meta-provided/` unchanged.
