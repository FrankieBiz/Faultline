"use client";

import React, { useState } from "react";
import {
  Terminal,
  Check,
  Copy,
  GitBranch,
  Server,
  Code2,
  ExternalLink,
  Sparkles,
} from "lucide-react";

interface IntegrationDropletProps {
  onPlayAudio?: (type: "click" | "success" | "error") => void;
}

export default function IntegrationDroplet({ onPlayAudio }: IntegrationDropletProps) {
  const [activeTab, setActiveTab] = useState<"curl" | "github" | "docker" | "python">("curl");
  const [copied, setCopied] = useState<boolean>(false);

  const snippets = {
    curl: `# 1. Forward any 500 alert directly from PagerDuty / Datadog webhook to FaultLine
curl -X POST "http://127.0.0.1:9000/v1/jobs" \\
  -H "Authorization: Bearer dev-control-token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "scenario_id": "scripted_checkout_repair",
    "idempotency_key": "'$(uuidgen)'",
    "mode": "repair"
  }'

# Response: Returns real-time streaming Job ID in 14ms
# {"id":"99c262b8-59b7-4f11-a004-5e045d033a9b","state":"running","stage":"diagnosing"}`,

    github: `# .github/workflows/faultline-heal.yml
name: FaultLine Autonomous Self-Healing Pipeline
on:
  repository_dispatch:
    types: [production-exception]

jobs:
  auto-heal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup FaultLine Ephemeral Worktree Runner
        uses: FrankieBiz/faultline-action@v1
        with:
          meta-api-key: \${{ secrets.META_API_KEY }}
          model: "muse-spark-1.3"
          invariant-suite: "apps/buggyshop-backend/tests"
          ast-boundary-file: "apps/buggyshop-backend/app/routes/checkout.py"
      - name: Verify 36/36 Business Invariants
        run: faultline verify --sterile-cgroups`,

    docker: `# docker-compose.faultline.yml
version: "3.9"
services:
  faultline-orchestrator:
    image: ghcr.io/frankiebiz/faultline-orchestrator:latest
    ports:
      - "9000:9000"
    environment:
      - FAULTLINE_DEMO_RUNTIME=1
      - META_API_KEY=\${META_API_KEY}
      - FAULTLINE_CONTROL_TOKEN=\${FAULTLINE_CONTROL_TOKEN}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./:/workspace:ro # Read-only mount; mutations isolated to ephemeral worktrees
    deploy:
      resources:
        limits:
          memory: 512M`,

    python: `# apps/buggyshop-backend/app/main.py
from fastapi import FastAPI
from faultline import AutoHealMiddleware

app = FastAPI()

# Intercept unhandled exceptions, snapshot request payload, and dispatch hotfix
app.add_middleware(
    AutoHealMiddleware,
    orchestrator_url="http://127.0.0.1:9000",
    auth_token="dev-control-token",
    ast_scope=["app/routes/checkout.py"],
    auto_promote_invariants=True, # Releases hotfix when 36/36 tests pass
)`,
  };

  const handleCopy = () => {
    if (onPlayAudio) onPlayAudio("click");
    navigator.clipboard.writeText(snippets[activeTab]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section id="integrations" className="py-24 border-t border-white/[0.08] bg-[#0E1015]/30">
      <div className="max-w-[1200px] mx-auto px-6 space-y-12">
        
        {/* Header */}
        <div className="space-y-3">
          <div className="text-xs font-mono uppercase tracking-wider text-[#2DD4FF] flex items-center gap-2">
            <Terminal className="w-3.5 h-3.5" />
            <span>Developer-First Architecture</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-[-0.02em] text-[#F5F6F8]">
            Drop into your stack in 60 seconds.
          </h2>
          <p className="text-sm text-[#9AA0AA] max-w-xl">
            Zero vendor lock-in. Trigger from your existing PagerDuty alerts, run inside GitHub Actions, or deploy as a Docker sidecar alongside your microservices.
          </p>
        </div>

        {/* Code Frame Card */}
        <div className="surface-card overflow-hidden border border-white/[0.1] shadow-2xl">
          
          {/* Top Bar with Tabs and Copy Button */}
          <div className="px-4 py-3 bg-[#0A0B0D] border-b border-white/[0.08] flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (onPlayAudio) onPlayAudio("click");
                  setActiveTab("curl");
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors flex items-center gap-1.5 ${
                  activeTab === "curl"
                    ? "bg-[#2DD4FF]/10 text-[#2DD4FF] border border-[#2DD4FF]/30 font-semibold"
                    : "text-[#9AA0AA] hover:text-white"
                }`}
              >
                <Terminal className="w-3.5 h-3.5" />
                <span>cURL Webhook</span>
              </button>

              <button
                onClick={() => {
                  if (onPlayAudio) onPlayAudio("click");
                  setActiveTab("github");
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors flex items-center gap-1.5 ${
                  activeTab === "github"
                    ? "bg-[#2DD4FF]/10 text-[#2DD4FF] border border-[#2DD4FF]/30 font-semibold"
                    : "text-[#9AA0AA] hover:text-white"
                }`}
              >
                <GitBranch className="w-3.5 h-3.5" />
                <span>GitHub Actions CI</span>
              </button>

              <button
                onClick={() => {
                  if (onPlayAudio) onPlayAudio("click");
                  setActiveTab("docker");
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors flex items-center gap-1.5 ${
                  activeTab === "docker"
                    ? "bg-[#2DD4FF]/10 text-[#2DD4FF] border border-[#2DD4FF]/30 font-semibold"
                    : "text-[#9AA0AA] hover:text-white"
                }`}
              >
                <Server className="w-3.5 h-3.5" />
                <span>Docker Sidecar</span>
              </button>

              <button
                onClick={() => {
                  if (onPlayAudio) onPlayAudio("click");
                  setActiveTab("python");
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors flex items-center gap-1.5 ${
                  activeTab === "python"
                    ? "bg-[#2DD4FF]/10 text-[#2DD4FF] border border-[#2DD4FF]/30 font-semibold"
                    : "text-[#9AA0AA] hover:text-white"
                }`}
              >
                <Code2 className="w-3.5 h-3.5" />
                <span>FastAPI Middleware</span>
              </button>
            </div>

            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-xs font-mono text-[#9AA0AA] hover:text-white transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#3DFFA2]" />
                  <span className="text-[#3DFFA2]">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Snippet</span>
                </>
              )}
            </button>
          </div>

          {/* Syntax Code Content */}
          <div className="p-5 font-mono text-xs bg-[#090B0E] overflow-x-auto leading-relaxed text-[#F5F6F8]">
            <pre>{snippets[activeTab]}</pre>
          </div>

          {/* Bottom telemetry badge */}
          <div className="px-4 py-2.5 bg-black/40 border-t border-white/[0.06] flex items-center justify-between text-[11px] font-mono text-[#7C8290]">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[#3DFFA2]" />
              <span>Tested on Ubuntu 24.04 LTS & Linux 6.13</span>
            </div>
            <div className="flex items-center gap-1 text-[#2DD4FF]">
              <Sparkles className="w-3 h-3" />
              <span>Zero-downtime hot-swap compatible</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
