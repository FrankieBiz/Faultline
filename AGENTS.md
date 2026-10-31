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

## Orchestration Model Rules & Multi-Model Architecture

### Response Format & Orca Child Dispatch Requirement
- **STRICT TRUTH IN ORCA CHILDREN**: Never fabricate, simulate, or claim models were used if they were not actually spun up as real Orca children (`orca worktree create ...` or `./scripts/orca-child.sh spawn ...`).
- If no Orca children were spun up in a turn (e.g. pure coordinator analysis, status check, or review), state explicitly:
```markdown
### Active Orca Children Spun Up:
*None for this turn.*
```
- When Orca children ARE spun up, list ONLY the real running children concisely:
```markdown
### Active Orca Children Spun Up:
- **<Agent Name>** (`<model>` via Orca worktree `<worktree_name>`): <Concise task description>
```
- All substantial coding, refactoring, and UI development MUST be done by spinning up real Orca child agents (Codex / Claude) in separate worktrees. Antigravity acts as coordinator.

### Orca Child Dispatch Protocol & Helper Commands
Use `./scripts/orca-child.sh` (or raw `orca` CLI) to manage child agents:
- **Spawn Codex (`gpt-6-astra` high effort)**:
  `./scripts/orca-child.sh spawn codex <worktree-name> "<prompt>"`
  *(Equivalent: `orca worktree create --name <name> --agent codex --model gpt-6-astra --effort high --prompt "<prompt>" --activate --json`)*
- **Spawn Claude (`claude-opus-5-5` high reasoning)**:
  `./scripts/orca-child.sh spawn claude <worktree-name> "<prompt>"`
  *(Equivalent: `orca worktree create --name <name> --agent claude --model claude-opus-5-5 --effort high --prompt "<prompt>" --activate --json`)*
- **Check Child Status**:
  `./scripts/orca-child.sh status <worktree-name>`
- **Read Child Output**:
  `./scripts/orca-child.sh read <worktree-name> [lines]`
- **Merge & Verify Child Worktree**:
  `./scripts/orca-child.sh merge <worktree-name>`
  *(Fetches child branch, merges, and automatically executes `make check`)*
- **Clean Child Worktree**:
  `./scripts/orca-child.sh clean <worktree-name>`

### Mandated Model Tiers (Strict Prohibition on Older Tiers)
- **STRICTLY FORBIDDEN**: Never orchestrate with older or lower-tier models (no Claude 3.5 Sonnet, no GPT-4o, no legacy tiers).
- **Mandated Frontier Tiers**:
  1. **OpenAI / Codex**: Use ONLY `gpt-6` or `gpt-6.1` (specifically `gpt-6.1-sol`, `gpt-6-astra`, high/xhigh effort).
  2. **Anthropic / Claude**: Use ONLY the highest frontier tier available (`claude-opus-5-5` / Opus with high reasoning).
  3. **DeepSeek**: Permitted and encouraged to utilize `deepseek-v4.1-flash` (or DeepSeek V3/R1 flash via `DEEPSEEK_API_KEY`) for rapid fuzzing, extraction, and auditor passes.
  4. **Meta Inference**: Target Meta Model API (`muse-spark-1.3`, `Llama-3.3-70B-Instruct`) for core hackathon domain generation (e.g., source repair).
  5. **Local Inference**: Local Ollama (`qwen2.5-coder:14b`, `7b`) at `http://localhost:11434/v1` for offline fallback.
  6. **Antigravity (Coordinator)**: Orca orchestration supervisor, task graph DAG controller, disjoint worktree/file partitioner, verification gatekeeper (`make check`), and zero-AI git finish executor.

### Functional Division of Labor
- **OpenAI GPT-6.1 (`gpt-6.1-sol`)**:
  - Assigned to **Deep Backend Engineering**: FastAPI endpoints, Pydantic v2 schemas, patch validation logic, test harnesses, and backend regression suites.
- **Anthropic Claude (`claude-opus-5-5` / high reasoning)**:
  - Assigned to **Frontend Ergonomics & Browser QA**: Next.js App Router UI, Playwright browser test visualization, Inspector panels, terminal aesthetics, and hackathon presentation/narrative.
- **DeepSeek (`deepseek-v4.1-flash`)**:
  - Assigned to **High-Throughput Extraction & Rapid Auditing**: Batch syntax/error analysis, edge-case test fuzzing, and rapid token scanning.
- **Antigravity (Coordinator)**:
  - Oversees the autonomous perfection loop: plans the feature DAG, partitions file boundaries to prevent merge conflicts, dispatches parallel workers, monitors progress reactively, executes verification gates (`make check`), and runs the zero-AI git finish protocol.

### Autonomous Perfection Loop & Finish Protocol
1. **Autonomous Execution**: When in loop mode, the coordinator plans what needs to be done, dispatches the frontier models to execute, reviews outputs, validates test suites, and pushes to main. Do not pause for routine confirmation—proceed autonomously while periodically grounding to ensure architectural alignment.
2. **No Diagrams Rule**: Never generate Mermaid diagrams or ASCII/plaintext diagram boxes. All concepts, workflows, and architectures must be presented in markdown lists, tables, or clean prose.
3. **Mandatory Git Finish Protocol**:
   - Verify all tests pass (`make check`).
   - Run `agent-finish "<imperative commit message>"` or `git finish "<message>"`.
   - Never commit with AI names (Claude, ChatGPT, Gemini, Anthropic, OpenAI) or `Co-Authored-By` lines. All commits must be attributed to `Francis Bisignano <frankabisignano@gmail.com>`.
   - Remote production must always be updated and green.
