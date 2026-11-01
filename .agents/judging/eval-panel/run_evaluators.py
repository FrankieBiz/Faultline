#!/usr/bin/env python3
"""
Multi-Model Evaluation Panel for FaultLine
Spins up cheap independent models:
1. DeepSeek (Hostile Meta Hackathon Judge Perspective)
2. DeepSeek (Real-World Developer & End-User Experience Perspective)
3. Llama 3.2 Local Ollama (Systems & Security Auditor Perspective)
"""

import os
import sys
import json
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

SYSTEM_CONTEXT = """
You are an expert evaluating FaultLine, a hackathon project built for Meta's Global AI Developer Hackathon (Indie Track).
Project Repository: FaultLine (Francis Bisignano / FrankieBiz).
Core Mission: Controlled browser QA and verified source repair for web applications, focused on silent checkout regressions in e-commerce.

Core Architectural Components:
1. Autonomous Playwright Crawler (`tools/browser-runner`): Crawls web applications, identifies silent failures (HTTP 500s, console errors, broken form submissions), and produces an executable, deterministic click-trail reproduction bundle.
2. Sandboxed Isolated Runtime (`services/repair-orchestrator`): Uses Linux Bubblewrap namespaces (user, network, PID) and aggregate systemd cgroup v2 limits (512 MiB, 64 tasks, 1 CPU) to run untrusted candidate code safely without leaking credentials.
3. Patch Engine & AST Validator: Applies unified diffs, recounts miscounted hunk headers, validates AST to ensure restricted imports and single-file modifications.
4. Verifier-Guided Repair Loop: Feeds contract specification and failure traces to Meta Model API (`muse-spark-1.3` / Llama-3.3-70B); candidate diffs must pass independent external HTTP and browser regression suites. If rejected, bounded gate findings are fed into attempt 2.
5. Developer Inspector UI (`web/inspector-ui`): Next.js App Router dashboard displaying live job status, Playwright trace previews, replay cursors, cgroup kernel telemetry, and pre-flight gate.
6. Verification Evidence: 1,211 automated tests passing across the repository (pytest, playwright, ruff, mypy), verified Bubblewrap cgroup isolation, and a 10-defect holdout evaluation corpus.

Current Realities and Honest Ground Truth:
- The live interactive demo features a registered e-commerce checkout failure (empty coupon -> None subtraction -> HTTP 500).
- An evaluation corpus contains 10 holdout defects and 11 candidate patches.
- Retained evaluation runs show DeepSeek v4-pro verified 18 of 20 runs across the corpus; Meta runs have been verified on controller replays.
- An earlier skeptical internal review rated the project 55/100 due to narrow defect scope, lack of firsthand user interviews, and need for live Meta trial repetition.
"""

def query_deepseek(prompt: str, role_desc: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "ERROR: DEEPSEEK_API_KEY not set"
    
    url = "https://api.deepseek.com/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": f"{SYSTEM_CONTEXT}\n\nYour Persona: {role_desc}"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 3000
    }
    
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },
        data=json.dumps(payload).encode("utf-8")
    )
    
    with urllib.request.urlopen(req, timeout=90) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["choices"][0]["message"]["content"]

def query_ollama(prompt: str, role_desc: str) -> str:
    url = "http://localhost:11434/api/generate"
    full_prompt = f"System: {SYSTEM_CONTEXT}\nRole: {role_desc}\n\nUser Task: {prompt}\n\nProvide your rigorous, objective evaluation report:"
    payload = {
        "model": "llama3.2:latest",
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": 1000,
            "temperature": 0.2
        }
    }
    req = urllib.request.Request(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8")
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["response"]

def run_evaluator_1():
    print("[1/3] Running Evaluator A: DeepSeek - Skeptical Meta Hackathon Judge...")
    role = "You are a skeptical, highly experienced Meta Hackathon Judge evaluating FaultLine against Meta's official 100-point rubric: Impact (30%), Meta AI Tooling (25%), Technical Depth (20%), Demo & Polish (25%)."
    prompt = """
Conduct an exhaustive, independent, brutal review of FaultLine from the perspective of an official Meta Hackathon Judge.

Address these specific dimensions in detail:
1. DOES IT ACTUALLY SOLVE A REAL PROBLEM OR IS IT HACKATHON THEATER?
   - Evaluate the problem: silent e-commerce checkout regressions.
   - Is an automated browser reproduction -> sandboxed repair -> verifier gate loop a commercially viable concept or an artificial demo?
   - Compare to existing tools (Sentry, Playwright test suites, GitHub Copilot Workspace, Cursor). Where does FaultLine genuinely add value?

2. META HACKATHON RUBRIC SCORING & DEDUCTIONS:
   - Impact (30 pts): Grade with specific score out of 30, evidence citations, and deductions.
   - Meta AI Tooling (25 pts): Grade with specific score out of 25. Scrutinize the Meta Model API integration, verifier guidance feedback, prompt structure, and the reliance on deterministic/DeepSeek fallback evidence.
   - Technical Depth (20 pts): Grade with specific score out of 20. Evaluate Bubblewrap sandboxing, cgroup v2 memory/task quotas, AST parsing, single-file diff recount.
   - Demo & Polish (25 pts): Grade with specific score out of 25. Evaluate the live demo flow, Inspector UI, judge orientation, and pitch narrative.
   - TOTAL SCORE OUT OF 100.

3. VULNERABILITIES DURING HOSTILE JUDGING Q&A:
   - What are the top 3 hardest questions a judge will ask that could blow up the demo or expose limitations?
   - How should the presenter answer them truthfully without compromising score?

Provide clear headings, quantitative scores, concrete deductions, and grounded conclusions.
"""
    t0 = time.time()
    report = query_deepseek(prompt, role)
    elapsed = time.time() - t0
    print(f"Evaluator A completed in {elapsed:.1f}s")
    out_file = OUTPUT_DIR / "report_deepseek_judge.md"
    out_file.write_text(f"# Independent Evaluation: Skeptical Meta Hackathon Judge\n**Model**: DeepSeek-V4.1 (Chat)\n**Elapsed Time**: {elapsed:.1f}s\n\n{report}\n")
    return "Evaluator A (DeepSeek Judge) Done"

def run_evaluator_2():
    print("[2/3] Running Evaluator B: DeepSeek - Developer & End-User Experience...")
    role = "You are a pragmatic Staff Software / Site Reliability Engineer who hates hype, evaluating FaultLine as a potential user and customer."
    prompt = """
Conduct an exhaustive, independent review of FaultLine from the perspective of an end-user / developer / engineering lead.

Address these specific dimensions in detail:
1. EASE OF USE & ONBOARDING:
   - Evaluate the developer interface: CLI commands (`faultline run`, `faultline gate`, `faultline init`) vs Inspector UI.
   - Setup friction: Linux kernel dependencies (Bubblewrap, cgroup v2, systemd user scopes), Python uv, Node.js. Is this too complex for the average frontend engineer?
   - Time-to-value: How fast can a developer go from zero to catching their first bug?

2. UI/UX OF THE INSPECTOR:
   - Evaluate the Next.js Inspector: visual hierarchy, real-time feedback, Playwright trace preview, cgroup metric graphs, pre-flight gate.
   - Is it informative or noisy? Does it give actionable confidence to a developer about to merge code?
   - Contrast the web UI with the CLI terminal output: which is better for real CI/CD?

3. FUNCTIONAL UTILITY & REAL-WORLD ADOPTION:
   - Does this actually work in a real engineering team's workflow?
   - The safety boundary: FaultLine does NOT auto-deploy to production; it produces a verified candidate patch and evidence bundle. Is that the right boundary, or does it reduce the magic?
   - Would you actually put `faultline gate` into your GitHub Actions PR check? Why or why not?

4. TOP 3 UX / PRODUCT RECOMMENDATIONS:
   - What are the 3 most critical ergonomics or workflow improvements needed before developers will love this?

Provide clear headings, candid critiques, and practical developer insights.
"""
    t0 = time.time()
    report = query_deepseek(prompt, role)
    elapsed = time.time() - t0
    print(f"Evaluator B completed in {elapsed:.1f}s")
    out_file = OUTPUT_DIR / "report_deepseek_user.md"
    out_file.write_text(f"# Independent Evaluation: End-User & Developer Experience\n**Model**: DeepSeek-V4.1 (Chat)\n**Elapsed Time**: {elapsed:.1f}s\n\n{report}\n")
    return "Evaluator B (DeepSeek User) Done"

def run_evaluator_3():
    print("[3/3] Running Evaluator C: Llama 3.2 (Local Ollama) - Systems & Code Auditor...")
    role = "You are a Principal Systems & Security Auditor evaluating the code quality, safety architecture, and functional execution of FaultLine."
    prompt = """
Evaluate FaultLine's code architecture, security sandbox, and functional correctness.

Address:
1. CODE ARCHITECTURE & QUALITY:
   - Evaluate the multi-tier architecture: FastAPI orchestrator, Playwright crawler, Bubblewrap isolation, AST validation, and Next.js frontend.
   - Assess code hygiene: 1,211 automated tests, strict mypy typing, ruff formatting. Is this genuine rigor or vanity metrics?

2. SECURITY & ISOLATION (BUBBLEWRAP & CGROUPS):
   - Assess the Linux Bubblewrap containment: user/net/PID namespaces, readonly filesystem mounts, bounded tmpfs.
   - Assess cgroup v2 limits (512 MiB, 64 tasks, 1 CPU). Does this prevent malicious or runaway LLM patches (fork bombs, OOMs, credential theft)?

3. FUNCTIONAL EXECUTION & THE REPAIR LOOP:
   - Does the repair loop actually work? How does the AST validator and hunk-recount mechanism handle faulty LLM diffs?
   - What are the potential failure modes (e.g. false positives where a bad patch passes tests, or flakiness in browser crawl)?

4. SUMMARY VERDICT ON CODE INTEGRITY:
   - Provide a final assessment on code and functional stability (Scale 1-10 with justification).
"""
    t0 = time.time()
    report = query_ollama(prompt, role)
    elapsed = time.time() - t0
    print(f"Evaluator C completed in {elapsed:.1f}s")
    out_file = OUTPUT_DIR / "report_llama_systems.md"
    out_file.write_text(f"# Independent Evaluation: Systems, Security & Code Integrity\n**Model**: Llama 3.2:latest (Local Ollama CPU)\n**Elapsed Time**: {elapsed:.1f}s\n\n{report}\n")
    return "Evaluator C (Llama 3.2 Systems) Done"

def main():
    print("=== Starting Cheap Independent Evaluator Panel ===")
    with ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(run_evaluator_1)
        f2 = executor.submit(run_evaluator_2)
        f3 = executor.submit(run_evaluator_3)
        
        for f in [f1, f2, f3]:
            print(f.result())
    print("=== All 3 Cheap Model Evaluators Completed Successfully ===")

if __name__ == "__main__":
    main()
