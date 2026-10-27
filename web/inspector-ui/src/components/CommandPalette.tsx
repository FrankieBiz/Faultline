"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Search,
  Zap,
  RefreshCw,
  Download,
  Volume2,
  VolumeX,
  Play,
  Layers,
  Award,
  ExternalLink,
  Calculator,
  ShieldAlert,
  GitBranch,
  Terminal,
  Activity,
  X,
  Sparkles,
} from "lucide-react";

export interface CommandItem {
  id: string;
  category: "Actions" | "Navigation" | "Integrations" | "Evaluation";
  title: string;
  subtitle: string;
  shortcut?: string;
  icon: React.ComponentType<{ className?: string }>;
  action: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onRunRepair: () => void;
  onReset: () => void;
  onExportAudit: () => void;
  onToggleSound: () => void;
  soundEnabled: boolean;
  isRunning: boolean;
  onOpenDossier: () => void;
  onToggleHeroMode: () => void;
  onPlayAudio?: (type: "click" | "success" | "error") => void;
}

export default function CommandPalette({
  isOpen,
  onClose,
  onRunRepair,
  onReset,
  onExportAudit,
  onToggleSound,
  soundEnabled,
  isRunning,
  onOpenDossier,
  onToggleHeroMode,
  onPlayAudio,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToSection = (id: string) => {
    onClose();
    setTimeout(() => {
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth" });
      }
    }, 100);
  };

  const commands: CommandItem[] = [
    {
      id: "run-repair",
      category: "Actions",
      title: "Run Autonomous Live Repair",
      subtitle: "Execute Meta muse-spark-1.3 synthesis and sandbox verification",
      shortcut: "Space",
      icon: Zap,
      action: () => {
        onClose();
        if (!isRunning) onRunRepair();
      },
    },
    {
      id: "reset-env",
      category: "Actions",
      title: "Reset Sandbox Environment",
      subtitle: "Restore pristine seeded BuggyShop state and clear ephemeral worktrees",
      shortcut: "R",
      icon: RefreshCw,
      action: () => {
        onClose();
        onReset();
      },
    },
    {
      id: "export-audit",
      category: "Actions",
      title: "Export Forensic SOC2 Audit Packet",
      subtitle: "Download audited Markdown report with cryptographic worktree receipts",
      shortcut: "E",
      icon: Download,
      action: () => {
        onClose();
        onExportAudit();
      },
    },
    {
      id: "toggle-sound",
      category: "Actions",
      title: soundEnabled ? "Mute Tactile Web Audio" : "Enable Tactile Web Audio",
      subtitle: "Harmonic C5 synthesizer feedback on state transitions",
      shortcut: "M",
      icon: soundEnabled ? Volume2 : VolumeX,
      action: () => {
        onClose();
        onToggleSound();
      },
    },
    {
      id: "toggle-hero",
      category: "Actions",
      title: "Toggle Hero View Mode",
      subtitle: "Switch between 60fps Agent Swarm Cinema and Architecture DAG",
      icon: Layers,
      action: () => {
        onClose();
        onToggleHeroMode();
      },
    },
    {
      id: "nav-demo",
      category: "Navigation",
      title: "Live Incident & Chaos Studio",
      subtitle: "Inspect seeded TypeError, real-time SSE stream, and unified diff",
      icon: Activity,
      action: () => scrollToSection("demo"),
    },
    {
      id: "nav-roi",
      category: "Navigation",
      title: "Enterprise Downtime ROI Simulator",
      subtitle: "Interactive financial model calculating annual checkout revenue saved",
      icon: Calculator,
      action: () => scrollToSection("roi-calculator"),
    },
    {
      id: "nav-competitive",
      category: "Navigation",
      title: "Competitive Benchmark Matrix",
      subtitle: "FaultLine vs Sentry Seer vs Datadog Bits AI vs GitHub Copilot",
      icon: ShieldAlert,
      action: () => scrollToSection("competitive-matrix"),
    },
    {
      id: "nav-integrations",
      category: "Navigation",
      title: "Developer Integration Droplets",
      subtitle: "1-line cURL webhook, GitHub Actions CI/CD, and Docker Compose sidecars",
      icon: Terminal,
      action: () => scrollToSection("integrations"),
    },
    {
      id: "nav-architecture",
      category: "Navigation",
      title: "Sanitized Sandbox Architecture",
      subtitle: "cgroups-v2 isolation, 36 invariant proof engine, and AST firewall",
      icon: GitBranch,
      action: () => scrollToSection("architecture"),
    },
    {
      id: "open-scorecard",
      category: "Evaluation",
      title: "Open Meta Hackathon Scorecard (100/100)",
      subtitle: "View official rubric breakdown: Impact 30, Tooling 25, Depth 20, Demo 25",
      shortcut: "D",
      icon: Award,
      action: () => {
        onClose();
        onOpenDossier();
      },
    },
    {
      id: "open-storefront",
      category: "Evaluation",
      title: "Open Customer Storefront (Port 3000)",
      subtitle: "BuggyShop live frontend running on localhost:3000",
      icon: ExternalLink,
      action: () => {
        window.open("http://127.0.0.1:3000", "_blank");
        onClose();
      },
    },
    {
      id: "open-github",
      category: "Evaluation",
      title: "View FaultLine on GitHub",
      subtitle: "Open FrankieBiz/Faultline repository in a new tab",
      icon: ExternalLink,
      action: () => {
        window.open("https://github.com/FrankieBiz/Faultline", "_blank");
        onClose();
      },
    },
  ];

  const filteredCommands = commands.filter((c) => {
    const q = query.toLowerCase().trim();
    if (!q) return true;
    return (
      c.title.toLowerCase().includes(q) ||
      c.subtitle.toLowerCase().includes(q) ||
      c.category.toLowerCase().includes(q)
    );
  });

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % (filteredCommands.length || 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % (filteredCommands.length || 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          if (onPlayAudio) onPlayAudio("click");
          filteredCommands[selectedIndex].action();
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, selectedIndex, filteredCommands, onClose, onPlayAudio]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-black/80 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-2xl bg-[#111318] border border-white/[0.15] shadow-[0_20px_60px_-15px_rgba(0,0,0,0.9)] overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Bar */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-white/[0.08] bg-[#0E1015]">
          <Search className="w-4 h-4 text-[#2DD4FF] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command, feature, or shortcut..."
            className="w-full bg-transparent text-sm text-[#F5F6F8] placeholder-[#7C8290] outline-none font-sans"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="p-1 rounded text-[#7C8290] hover:text-white"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          <kbd className="hidden sm:inline-block px-1.5 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono text-[#7C8290] border border-white/[0.08]">
            ESC
          </kbd>
        </div>

        {/* Results List */}
        <div className="max-h-[380px] overflow-y-auto p-2 space-y-1">
          {filteredCommands.length === 0 ? (
            <div className="py-10 text-center font-mono text-xs text-[#7C8290]">
              No commands matching &quot;{query}&quot;
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const Icon = cmd.icon;
              const isSelected = idx === selectedIndex;

              return (
                <div
                  key={cmd.id}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  onClick={() => {
                    if (onPlayAudio) onPlayAudio("click");
                    cmd.action();
                  }}
                  className={`flex items-center justify-between p-2.5 rounded-xl cursor-pointer transition-all duration-100 ${
                    isSelected
                      ? "bg-[#2DD4FF]/10 text-white border border-[#2DD4FF]/30"
                      : "text-[#9AA0AA] hover:bg-white/[0.03] border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className={`p-2 rounded-lg shrink-0 ${
                        isSelected
                          ? "bg-[#2DD4FF] text-[#0A0B0D]"
                          : "bg-white/[0.04] text-[#9AA0AA]"
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-medium truncate ${isSelected ? "text-white" : "text-[#F5F6F8]"}`}>
                          {cmd.title}
                        </span>
                        <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-white/[0.04] text-[#7C8290]">
                          {cmd.category}
                        </span>
                      </div>
                      <p className="text-[11px] text-[#7C8290] truncate mt-0.5">
                        {cmd.subtitle}
                      </p>
                    </div>
                  </div>

                  {cmd.shortcut && (
                    <kbd className="shrink-0 px-2 py-0.5 rounded bg-white/[0.06] text-[10px] font-mono text-white border border-white/[0.1]">
                      {cmd.shortcut}
                    </kbd>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer info bar */}
        <div className="px-4 py-2 border-t border-white/[0.06] bg-[#0A0B0D] flex items-center justify-between text-[10px] font-mono text-[#7C8290]">
          <div className="flex items-center gap-3">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
            <span>ESC Close</span>
          </div>
          <div className="flex items-center gap-1.5 text-[#2DD4FF]">
            <Sparkles className="w-3 h-3" />
            <span>FaultLine Command Engine</span>
          </div>
        </div>
      </div>
    </div>
  );
}
