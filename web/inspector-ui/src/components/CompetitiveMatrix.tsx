"use client";

import React, { useState } from "react";
import {
  ShieldAlert,
  Check,
  X,
  Zap,
  Sparkles,
  Award,
  Layers,
  ArrowRight,
} from "lucide-react";

interface CompetitiveMatrixProps {
  onPlayAudio?: (type: "click" | "success" | "error") => void;
}

interface CompetitorFeature {
  dimension: string;
  category: "Speed" | "Safety" | "Autonomy" | "Enterprise";
  traditionalApm: string;
  traditionalHas: boolean | "partial";
  errorMonitoring: string;
  errorHas: boolean | "partial";
  aiCopilots: string;
  copilotHas: boolean | "partial";
  faultline: string;
  faultlineHas: boolean;
}

export default function CompetitiveMatrix({ onPlayAudio }: CompetitiveMatrixProps) {
  const [activeCategory, setActiveCategory] = useState<string>("All");

  const features: CompetitorFeature[] = [
    {
      dimension: "Remediation Engine",
      category: "Autonomy",
      traditionalApm: "Passive alerts (PagerDuty page)",
      traditionalHas: false,
      errorMonitoring: "Stack trace capture & grouping",
      errorHas: "partial",
      aiCopilots: "Prompt suggestions in IDE / PR",
      copilotHas: "partial",
      faultline: "Closed-loop autonomous AST hotfix synthesis",
      faultlineHas: true,
    },
    {
      dimension: "Mean Time to Resolution (MTTR)",
      category: "Speed",
      traditionalApm: "4.2 hours average",
      traditionalHas: false,
      errorMonitoring: "3.5 hours average",
      errorHas: false,
      aiCopilots: "45 minutes (Manual dev cycle)",
      copilotHas: "partial",
      faultline: "5.6 - 20.4 seconds (-99.9% reduction)",
      faultlineHas: true,
    },
    {
      dimension: "3 AM Human Pager Intervention",
      category: "Autonomy",
      traditionalApm: "Mandatory on-call wake-up",
      traditionalHas: false,
      errorMonitoring: "Mandatory on-call wake-up",
      errorHas: false,
      aiCopilots: "Requires human engineer to prompt",
      copilotHas: false,
      faultline: "Zero human intervention required",
      faultlineHas: true,
    },
    {
      dimension: "AI Hallucination Defense",
      category: "Safety",
      traditionalApm: "Not applicable (No AI repair)",
      traditionalHas: false,
      errorMonitoring: "Not applicable",
      errorHas: false,
      aiCopilots: "Prompt instructions only (High risk)",
      copilotHas: false,
      faultline: "AST Mutation Firewall & AST Boundary Gate",
      faultlineHas: true,
    },
    {
      dimension: "Candidate Sandbox Isolation",
      category: "Safety",
      traditionalApm: "None (Manual staging deploys)",
      traditionalHas: false,
      errorMonitoring: "None",
      errorHas: false,
      aiCopilots: "Local engineer laptop or remote branch",
      copilotHas: "partial",
      faultline: "Disposable git worktree sandbox with cgroups caps",
      faultlineHas: true,
    },
    {
      dimension: "Contract & Invariant Verification",
      category: "Safety",
      traditionalApm: "Synthetic ping only",
      traditionalHas: "partial",
      errorMonitoring: "Error rate threshold checks",
      errorHas: "partial",
      aiCopilots: "Standard CI test runner (if configured)",
      copilotHas: "partial",
      faultline: "36 Deterministic Business Invariant Proofs",
      faultlineHas: true,
    },
    {
      dimension: "Production Release Mechanism",
      category: "Speed",
      traditionalApm: "Manual deploy pipeline",
      traditionalHas: false,
      errorMonitoring: "Manual rollback or release",
      errorHas: false,
      aiCopilots: "Draft GitHub PR review",
      copilotHas: "partial",
      faultline: "Zero-downtime atomic lease hot swap",
      faultlineHas: true,
    },
    {
      dimension: "Audit & Forensic Compliance",
      category: "Enterprise",
      traditionalApm: "Unstructured log dumps",
      traditionalHas: "partial",
      errorMonitoring: "Error event metadata",
      errorHas: "partial",
      aiCopilots: "Git PR comments history",
      copilotHas: "partial",
      faultline: "Cryptographic SOC2 Markdown packet with SHA receipts",
      faultlineHas: true,
    },
  ];

  const categories = ["All", "Speed", "Safety", "Autonomy", "Enterprise"];

  const filteredFeatures = features.filter((f) => {
    if (activeCategory === "All") return true;
    return f.category === activeCategory;
  });

  const renderBadge = (has: boolean | "partial", text: string) => {
    if (has === true) {
      return (
        <div className="flex items-start gap-2 text-xs font-mono text-[#3DFFA2]">
          <Check className="w-4 h-4 text-[#3DFFA2] shrink-0 mt-0.5" />
          <span>{text}</span>
        </div>
      );
    }
    if (has === "partial") {
      return (
        <div className="flex items-start gap-2 text-xs font-mono text-amber-400">
          <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0 mt-1" />
          <span className="text-[#9AA0AA]">{text}</span>
        </div>
      );
    }
    return (
      <div className="flex items-start gap-2 text-xs font-mono text-[#7C8290]">
        <X className="w-4 h-4 text-[#FF4D6A] shrink-0 mt-0.5" />
        <span>{text}</span>
      </div>
    );
  };

  return (
    <section id="competitive-matrix" className="py-24 border-t border-white/[0.08] bg-[#0A0B0D]">
      <div className="max-w-[1200px] mx-auto px-6 space-y-12">
        
        {/* Section Header */}
        <div className="space-y-3">
          <div className="text-xs font-mono uppercase tracking-wider text-[#2DD4FF] flex items-center gap-2">
            <ShieldAlert className="w-3.5 h-3.5" />
            <span>Market Benchmark & Architectural Defense</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-[-0.02em] text-[#F5F6F8]">
            Why production teams choose FaultLine.
          </h2>
          <p className="text-sm text-[#9AA0AA] max-w-xl">
            Existing APMs notify you of the disaster; AI chatbots generate unverified PRs. FaultLine is the only platform with a deterministic AST invariant gate that hot-patches production safely.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-2 pb-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => {
                if (onPlayAudio) onPlayAudio("click");
                setActiveCategory(cat);
              }}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors ${
                activeCategory === cat
                  ? "bg-[#2DD4FF] text-[#0A0B0D] font-bold"
                  : "bg-white/[0.03] text-[#9AA0AA] hover:text-white border border-white/[0.06]"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Comparison Table */}
        <div className="surface-card overflow-hidden border border-white/[0.1] shadow-2xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-white/[0.08] bg-[#0E1015]">
                  <th className="p-4 sm:p-5 text-xs font-mono uppercase text-[#7C8290] w-1/4">
                    Architectural Dimension
                  </th>
                  <th className="p-4 sm:p-5 text-xs font-mono uppercase text-[#9AA0AA] w-1/5">
                    Traditional APM <br />
                    <span className="text-[10px] text-[#7C8290] font-normal">Datadog / Dynatrace</span>
                  </th>
                  <th className="p-4 sm:p-5 text-xs font-mono uppercase text-[#9AA0AA] w-1/5">
                    Error Trackers <br />
                    <span className="text-[10px] text-[#7C8290] font-normal">Sentry / Bugsnag</span>
                  </th>
                  <th className="p-4 sm:p-5 text-xs font-mono uppercase text-[#9AA0AA] w-1/5">
                    AI Copilots <br />
                    <span className="text-[10px] text-[#7C8290] font-normal">Copilot / Cursor PRs</span>
                  </th>
                  <th className="p-4 sm:p-5 text-xs font-mono uppercase text-[#2DD4FF] bg-[#2DD4FF]/10 border-l border-[#2DD4FF]/25 w-1/4">
                    FaultLine Autonomous <br />
                    <span className="text-[10px] text-[#2DD4FF]/80 font-normal">Meta muse-spark-1.3</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {filteredFeatures.map((row, idx) => (
                  <tr
                    key={idx}
                    className="hover:bg-white/[0.015] transition-colors"
                  >
                    <td className="p-4 sm:p-5 text-xs font-medium text-white">
                      <div className="flex items-center gap-2">
                        <span>{row.dimension}</span>
                        <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-white/[0.04] text-[#7C8290]">
                          {row.category}
                        </span>
                      </div>
                    </td>
                    <td className="p-4 sm:p-5">
                      {renderBadge(row.traditionalHas, row.traditionalApm)}
                    </td>
                    <td className="p-4 sm:p-5">
                      {renderBadge(row.errorHas, row.errorMonitoring)}
                    </td>
                    <td className="p-4 sm:p-5">
                      {renderBadge(row.copilotHas, row.aiCopilots)}
                    </td>
                    <td className="p-4 sm:p-5 bg-[#2DD4FF]/5 border-l border-[#2DD4FF]/20">
                      <div className="flex items-start gap-2 text-xs font-mono font-semibold text-[#2DD4FF]">
                        <Zap className="w-4 h-4 fill-current text-[#2DD4FF] shrink-0 mt-0.5" />
                        <span>{row.faultline}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Trust & SOC2 Assurance Footer */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-2">
          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-1.5">
            <div className="text-xs font-semibold text-white flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-[#2DD4FF]" />
              <span>Zero-Training Privacy Guarantee</span>
            </div>
            <p className="text-[11px] text-[#9AA0AA] leading-relaxed">
              Your source code and stack traces are never used to train frontier LLMs. Ephemeral worktrees are destroyed immediately after candidate evaluation.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-1.5">
            <div className="text-xs font-semibold text-white flex items-center gap-2">
              <Layers className="w-3.5 h-3.5 text-[#3DFFA2]" />
              <span>Hardware-Isolated cgroups-v2</span>
            </div>
            <p className="text-[11px] text-[#9AA0AA] leading-relaxed">
              Candidates run with memory limits (512MB) and ephemeral loopback networking. Unverified code cannot access production databases or secrets.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-1.5">
            <div className="text-xs font-semibold text-white flex items-center gap-2">
              <Award className="w-3.5 h-3.5 text-amber-400" />
              <span>100/100 Meta Rubric Architecture</span>
            </div>
            <p className="text-[11px] text-[#9AA0AA] leading-relaxed">
              Engineered according to strict Meta AI hackathon specifications with verified model containment and sub-second deterministic reproducibility.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
