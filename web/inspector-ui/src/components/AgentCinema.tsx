"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  Play,
  Pause,
  RotateCcw,
  Sparkles,
  Zap,
  Activity,
  Terminal,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Cpu,
  Monitor,
  Code2,
  ChevronRight,
  Layers,
  ArrowRight,
  Check,
} from "lucide-react";

interface AgentCinemaProps {
  onTriggerRealRun?: () => void;
  isRealRunActive?: boolean;
}

interface AgentDetail {
  id: string;
  name: string;
  badge: string;
  role: string;
  engine: string;
  metrics: { label: string; value: string }[];
  outputTitle: string;
  outputContent: string;
}

const AGENTS: Record<string, AgentDetail> = {
  sentinel: {
    id: "sentinel",
    name: "01 // SENTRY SENTINEL",
    badge: "Port 8000 Observer",
    role: "Exception Telemetry Interception",
    engine: "FastAPI Middleware & Playwright Hook",
    metrics: [
      { label: "Capture Latency", value: "18ms" },
      { label: "Stacktrace Frame", value: "checkout.py:43" },
      { label: "Defect Type", value: "TypeError (NoneType)" },
    ],
    outputTitle: "Captured Production Exception Snapshot",
    outputContent: `POST /checkout HTTP/1.1 -> 500 Internal Server Error
TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'
File "apps/buggyshop-backend/app/routes/checkout.py", line 43, in checkout
  total = subtotal - discount
  ^^^ discount is None when coupon is omitted or invalid`,
  },
  "muse-spark": {
    id: "muse-spark",
    name: "02 // META MUSE SPARK 1.3",
    badge: "Meta Model API",
    role: "AST Differential Patch Synthesis",
    engine: "Meta Muse Spark 1.3 / Llama-3.3-70B",
    metrics: [
      { label: "Tokens Emitted", value: "48 tokens" },
      { label: "Emission Speed", value: "114 tok/sec" },
      { label: "AST Guardrail", value: "1 file, 0 new imports" },
    ],
    outputTitle: "AST-Bounded Synthesized Patch",
    outputContent: `--- a/apps/buggyshop-backend/app/routes/checkout.py
+++ b/apps/buggyshop-backend/app/routes/checkout.py
@@ -42,3 +42,3 @@
-    discount = cast(int, discounts.get(coupon_code))
+    discount = cast(int, discounts.get(coupon_code, 0))`,
  },
  verifier: {
    id: "verifier",
    name: "03 // SANDBOX EVALUATOR",
    badge: "cgroups-v2 Sandbox",
    role: "Automated Browser & Invariant Gate",
    engine: "Chromium 130 + Pytest Regression Suite",
    metrics: [
      { label: "Invariants Asserted", value: "36 / 36 PASS" },
      { label: "Execution Sandbox", value: "cgroups-v2 (42.4 MB)" },
      { label: "Clean Exit Code", value: "0 (Production Ready)" },
    ],
    outputTitle: "Production Readiness Invariant Receipt",
    outputContent: `[PASS] Invariants Verified: 36/36
[PASS] browser.launch (Chromium 130 headless)
[PASS] checkout.form.visible & coupon.normalization
[PASS] receipt.visible -> Order #FL-9942 generated ($19.99 paid)
[PASS] zero regressions across 351 contract assertions`,
  },
};

export default function AgentCinema({ onTriggerRealRun, isRealRunActive }: AgentCinemaProps) {
  // Cinema playback state: 9000ms total timeline (representing 1.14s real-time at readable inspection pace)
  const totalDurationMs = 9000;
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [currentMs, setCurrentMs] = useState<number>(0);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);
  const [activeTab, setActiveTab] = useState<"swarm" | "browser" | "diff">("swarm");
  const [selectedAgent, setSelectedAgent] = useState<string>("muse-spark");

  const animFrameRef = useRef<number | null>(null);
  const lastTimestampRef = useRef<number | null>(null);

  // Check prefers-reduced-motion
  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setIsPlaying(false);
    }
  }, []);

  // Animation Loop: 60fps compositor-friendly ticker
  useEffect(() => {
    if (!isPlaying) {
      lastTimestampRef.current = null;
      return;
    }

    const step = (now: number) => {
      if (lastTimestampRef.current === null) {
        lastTimestampRef.current = now;
      }
      const delta = (now - lastTimestampRef.current) * playbackSpeed;
      lastTimestampRef.current = now;

      setCurrentMs((prev) => {
        const next = prev + delta;
        // Loop back to start after reaching total duration
        if (next >= totalDurationMs) {
          return 0;
        }
        return next;
      });

      animFrameRef.current = requestAnimationFrame(step);
    };

    animFrameRef.current = requestAnimationFrame(step);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [isPlaying, playbackSpeed]);

  // Structured timeline phases (scaled for cinematic human readability):
  // 0 - 2000ms: Phase 1 — Exception Intercept (Sentinel)
  // 2000 - 5500ms: Phase 2 — AST Patch Synthesis (Muse Spark)
  // 5500 - 7800ms: Phase 3 — Sandbox Invariant Verification (Verifier)
  // 7800 - 9000ms: Phase 4 — Production Restored / Green Checkout Receipt (Hold & Celebrate)
  const phase = useMemo(() => {
    if (currentMs < 2000) return "sentinel";
    if (currentMs < 5500) return "muse-spark";
    if (currentMs < 7800) return "verifier";
    return "healed";
  }, [currentMs]);

  // Real-world execution time counter: mapped 0s -> 1.14s
  const realWorldSec = useMemo(() => {
    return Math.min(1.14, (currentMs / totalDurationMs) * 1.14).toFixed(2);
  }, [currentMs]);

  // Muse Spark typing tokens calculation
  const museTokens = useMemo(() => {
    const fullText = "discount = cast(int, discounts.get(coupon_code, 0))";
    if (currentMs < 2000) return "";
    if (currentMs >= 5500) return fullText;
    const progress = (currentMs - 2000) / 3500;
    const charCount = Math.floor(progress * fullText.length);
    return fullText.slice(0, charCount);
  }, [currentMs]);

  // Verifier invariant check counter (0 to 36)
  const invariantCount = useMemo(() => {
    if (currentMs < 5500) return 0;
    if (currentMs >= 7800) return 36;
    const progress = (currentMs - 5500) / 2300;
    return Math.min(36, Math.floor(progress * 36));
  }, [currentMs]);

  // Browser simulated cursor coordinates (GPU-friendly percentages)
  const browserCursor = useMemo(() => {
    if (currentMs < 1500) {
      const p = currentMs / 1500;
      return { x: 30 + p * 35, y: 40 + p * 15, clicking: false };
    }
    if (currentMs < 2200) {
      return { x: 65, y: 55, clicking: true };
    }
    if (currentMs < 5500) {
      const p = (currentMs - 2200) / 3300;
      return { x: 65 + p * 15, y: 55 + p * 25, clicking: false };
    }
    if (currentMs < 6800) {
      return { x: 80, y: 80, clicking: true };
    }
    return { x: 88, y: 85, clicking: false };
  }, [currentMs]);

  return (
    <div className="surface-card rounded-2xl border border-white/[0.08] overflow-hidden shadow-2xl relative bg-[#0A0B0D]">
      
      {/* 1. HUD CONTROL BAR */}
      <div className="px-5 py-3.5 bg-[#111318]/90 border-b border-white/[0.06] flex flex-wrap items-center justify-between gap-4 relative z-10">
        
        {/* Left: Cockpit status badge */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] text-xs font-mono">
            <span
              className={`w-2 h-2 rounded-full transition-colors duration-300 ${
                phase === "sentinel"
                  ? "bg-[#FF4D6A]"
                  : phase === "muse-spark"
                  ? "bg-[#2DD4FF]"
                  : "bg-[#3DFFA2]"
              }`}
            />
            <span className="text-[#F5F6F8] font-semibold">SWARM CINEMA</span>
            <span className="text-[#7C8290]">•</span>
            <span className="text-[#2DD4FF] uppercase tracking-wider text-[11px] font-bold">
              {phase === "sentinel"
                ? "SENTRY INTERCEPT"
                : phase === "muse-spark"
                ? "MUSE SPARK SYNTHESIS"
                : phase === "verifier"
                ? "PLAYWRIGHT VERIFYING"
                : "PRODUCTION RESTORED"}
            </span>
          </div>

          <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-[#7C8290]">
            <span>Real Runtime: <strong className="text-white">{realWorldSec}s</strong></span>
            <span>•</span>
            <span>Inspection Replay</span>
          </div>
        </div>

        {/* Center: View Switcher Tabs */}
        <div className="flex items-center p-1 rounded-xl bg-black/40 border border-white/[0.06] text-xs font-mono">
          <button
            onClick={() => setActiveTab("swarm")}
            aria-selected={activeTab === "swarm"}
            role="tab"
            className={`px-3 py-1 rounded-lg transition-colors flex items-center gap-1.5 ${
              activeTab === "swarm"
                ? "bg-[#2DD4FF] text-[#0A0B0D] font-semibold shadow-sm"
                : "text-[#9AA0AA] hover:text-white"
            }`}
          >
            <Layers className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>Agent Triad</span>
          </button>
          <button
            onClick={() => setActiveTab("browser")}
            aria-selected={activeTab === "browser"}
            role="tab"
            className={`px-3 py-1 rounded-lg transition-colors flex items-center gap-1.5 ${
              activeTab === "browser"
                ? "bg-[#2DD4FF] text-[#0A0B0D] font-semibold shadow-sm"
                : "text-[#9AA0AA] hover:text-white"
            }`}
          >
            <Monitor className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>Virtual Browser</span>
          </button>
          <button
            onClick={() => setActiveTab("diff")}
            aria-selected={activeTab === "diff"}
            role="tab"
            className={`px-3 py-1 rounded-lg transition-colors flex items-center gap-1.5 ${
              activeTab === "diff"
                ? "bg-[#2DD4FF] text-[#0A0B0D] font-semibold shadow-sm"
                : "text-[#9AA0AA] hover:text-white"
            }`}
          >
            <Code2 className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>Source Diff</span>
          </button>
        </div>

        {/* Right: Playback Controls & Speed Multipliers */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsPlaying(!isPlaying)}
            aria-label={isPlaying ? "Pause cinema playback" : "Start cinema playback"}
            className="p-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-white transition-colors"
          >
            {isPlaying ? (
              <Pause className="w-4 h-4 fill-current" strokeWidth={1.5} />
            ) : (
              <Play className="w-4 h-4 fill-current text-[#2DD4FF]" strokeWidth={1.5} />
            )}
          </button>

          <button
            onClick={() => setCurrentMs(0)}
            aria-label="Replay simulation"
            className="p-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-[#9AA0AA] hover:text-white transition-colors"
          >
            <RotateCcw className="w-4 h-4" strokeWidth={1.5} />
          </button>

          {/* Speed Selector */}
          <div className="flex items-center bg-black/50 rounded-lg border border-white/[0.06] p-0.5 text-[11px] font-mono">
            {[0.5, 1, 2].map((speed) => (
              <button
                key={speed}
                onClick={() => setPlaybackSpeed(speed)}
                aria-label={`Set speed to ${speed}x`}
                className={`px-2 py-0.5 rounded transition-colors ${
                  playbackSpeed === speed
                    ? "bg-white/[0.15] text-[#2DD4FF] font-semibold"
                    : "text-[#7C8290] hover:text-[#9AA0AA]"
                }`}
              >
                {speed}x
              </button>
            ))}
          </div>

          {/* Live Production Trigger Button */}
          {onTriggerRealRun && (
            <button
              onClick={onTriggerRealRun}
              disabled={isRealRunActive}
              className="ml-2 btn-press px-3 py-1 rounded-lg bg-[#2DD4FF] hover:bg-[#2DD4FF]/90 text-xs font-mono font-semibold text-[#0A0B0D] transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              <Zap className="w-3 h-3 fill-current" strokeWidth={1.5} />
              <span className="hidden md:inline">Run Live On Port 9000</span>
              <span className="md:hidden">Run Live</span>
            </button>
          )}
        </div>
      </div>

      {/* 2. TIMELINE SCRUBBER STRIP */}
      <div className="px-5 py-2 bg-black/40 border-b border-white/[0.04] flex items-center gap-4 text-xs font-mono">
        <span className="text-[#2DD4FF] shrink-0 w-16 font-semibold">
          {((currentMs / totalDurationMs) * 1.14).toFixed(2)}s / 1.14s
        </span>

        {/* Interactive Scrub Range Bar */}
        <div className="relative flex-1 h-3 flex items-center">
          <input
            type="range"
            min={0}
            max={totalDurationMs}
            value={currentMs}
            aria-label="Timeline position"
            onChange={(e) => {
              setCurrentMs(Number(e.target.value));
              setIsPlaying(false);
            }}
            className="w-full h-1 bg-white/[0.1] rounded-lg appearance-none cursor-pointer accent-[#2DD4FF]"
          />

          {/* Milestone markers */}
          <div className="absolute left-[0%] -top-1 w-1.5 h-3 bg-[#FF4D6A] rounded-full" title="0.00s: HTTP 500 TypeError" />
          <div className="absolute left-[22.2%] -top-1 w-1.5 h-3 bg-[#2DD4FF] rounded-full" title="0.25s: Muse Spark Synthesis" />
          <div className="absolute left-[61.1%] -top-1 w-1.5 h-3 bg-[#2DD4FF] rounded-full" title="0.70s: Playwright Invariants" />
          <div className="absolute left-[86.6%] -top-1 w-1.5 h-3 bg-[#3DFFA2] rounded-full" title="1.14s: Green Receipt Healed" />
        </div>

        <span className="text-[#7C8290] shrink-0 text-[11px]">100% Deterministic</span>
      </div>

      {/* 3. MAIN CINEMA STAGE */}
      <div className="p-6 md:p-8 min-h-[460px] flex flex-col justify-center relative">
        
        {/* VIEW 1: AGENT TRIAD SWARM HUD */}
        {activeTab === "swarm" && (
          <div className="space-y-6 relative">
            
            {/* SVG Connecting Cyber Energy Cables */}
            <svg
              className="absolute inset-0 w-full h-full pointer-events-none hidden md:block"
              style={{ zIndex: 0 }}
            >
              {/* Cable 1: Sentinel to Muse Spark */}
              <line
                x1="28%"
                y1="40%"
                x2="38%"
                y2="40%"
                stroke="rgba(255,255,255,0.08)"
                strokeWidth="2"
              />
              {currentMs >= 1800 && (
                <line
                  x1="28%"
                  y1="40%"
                  x2="38%"
                  y2="40%"
                  stroke="#2DD4FF"
                  strokeWidth="2"
                  strokeDasharray="6 4"
                />
              )}

              {/* Cable 2: Muse Spark to Verifier */}
              <line
                x1="62%"
                y1="40%"
                x2="72%"
                y2="40%"
                stroke="rgba(255,255,255,0.08)"
                strokeWidth="2"
              />
              {currentMs >= 5200 && (
                <line
                  x1="62%"
                  y1="40%"
                  x2="72%"
                  y2="40%"
                  stroke="#3DFFA2"
                  strokeWidth="2"
                  strokeDasharray="6 4"
                />
              )}
            </svg>

            {/* 3 Floating Agent Pods Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5 relative z-10">
              
              {/* POD 1: SENTINEL OBSERVER */}
              <button
                type="button"
                onClick={() => setSelectedAgent("sentinel")}
                aria-pressed={selectedAgent === "sentinel"}
                className={`text-left p-5 rounded-xl border transition-all duration-200 relative bg-[#111318] ${
                  phase === "sentinel"
                    ? "border-[#FF4D6A] shadow-[0_0_20px_-5px_rgba(255,77,106,0.3)] ring-1 ring-[#FF4D6A]"
                    : "border-white/[0.08] hover:border-white/[0.15]"
                }`}
              >
                {/* Pod Header */}
                <div className="flex items-center justify-between mb-3 text-xs font-mono">
                  <span className="flex items-center gap-1.5 text-[#FF4D6A] font-semibold">
                    <AlertTriangle className="w-4 h-4" strokeWidth={1.5} />
                    <span>01 // SENTINEL</span>
                  </span>
                  <span className="px-2 py-0.5 rounded bg-white/[0.04] text-[10px] text-[#7C8290]">
                    Port 8000
                  </span>
                </div>

                <div className="text-sm font-semibold text-white mb-1.5">
                  Exception Interception
                </div>

                <p className="text-xs text-[#9AA0AA] leading-relaxed mb-4">
                  Captures live stack trace from FastAPI and freezes the reproducer AST frame.
                </p>

                {/* Crash Snapshot Terminal */}
                <div className="p-3 rounded-lg bg-black/60 border border-white/[0.06] font-mono text-[11px] space-y-1">
                  <div className="flex items-center justify-between text-[#FF4D6A]">
                    <span>POST /checkout</span>
                    <span className="font-bold">500 ERROR</span>
                  </div>
                  <div className="text-[#7C8290] text-[10px] truncate">
                    TypeError: unsupported operand &apos;-&apos;
                  </div>
                  <div className="text-[10px] text-[#9AA0AA] flex items-center justify-between pt-1 border-t border-white/[0.04]">
                    <span>checkout.py:43</span>
                    <span className={phase === "sentinel" ? "text-[#FF4D6A]" : "text-[#7C8290]"}>
                      {phase === "sentinel" ? "CAPTURING..." : "INTERCEPTED"}
                    </span>
                  </div>
                </div>

                {/* Pod Bottom Metric */}
                <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-mono text-[#7C8290]">
                  <span>Capture Latency</span>
                  <span className="text-white font-semibold">18ms</span>
                </div>
              </button>

              {/* POD 2: META MUSE SPARK 1.3 */}
              <button
                type="button"
                onClick={() => setSelectedAgent("muse-spark")}
                aria-pressed={selectedAgent === "muse-spark"}
                className={`text-left p-5 rounded-xl border transition-all duration-200 relative bg-[#111318] ${
                  phase === "muse-spark"
                    ? "border-[#2DD4FF] shadow-[0_0_20px_-5px_rgba(45,212,255,0.3)] ring-1 ring-[#2DD4FF]"
                    : "border-white/[0.08] hover:border-white/[0.15]"
                }`}
              >
                {/* Pod Header */}
                <div className="flex items-center justify-between mb-3 text-xs font-mono">
                  <span className="flex items-center gap-1.5 text-[#2DD4FF] font-semibold">
                    <Sparkles className="w-4 h-4" strokeWidth={1.5} />
                    <span>02 // MUSE SPARK</span>
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#2DD4FF]/10 text-[10px] text-[#2DD4FF]">
                    Meta Model API
                  </span>
                </div>

                <div className="text-sm font-semibold text-white mb-1.5">
                  AST Patch Synthesis
                </div>

                <p className="text-xs text-[#9AA0AA] leading-relaxed mb-4">
                  Generates bounded Python source repair with integer-default type guards.
                </p>

                {/* Live Typing Code Stream */}
                <div className="p-3 rounded-lg bg-black/60 border border-white/[0.06] font-mono text-[11px] min-h-[68px] relative">
                  <div className="text-[10px] text-[#7C8290] mb-1">Generated AST Patch:</div>
                  <div className="text-[#2DD4FF] break-all leading-tight font-mono">
                    {museTokens || <span className="text-[#7C8290] italic">Awaiting prompt...</span>}
                    {phase === "muse-spark" && (
                      <span className="inline-block w-1.5 h-3.5 bg-[#2DD4FF] ml-1 align-middle" />
                    )}
                  </div>
                </div>

                {/* Pod Bottom Metric */}
                <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-mono text-[#7C8290]">
                  <span>Emission Rate</span>
                  <span className="text-[#2DD4FF] font-semibold">
                    {phase === "muse-spark" ? "114 tok/s" : "48 tokens total"}
                  </span>
                </div>
              </button>

              {/* POD 3: SANDBOX EVALUATOR */}
              <button
                type="button"
                onClick={() => setSelectedAgent("verifier")}
                aria-pressed={selectedAgent === "verifier"}
                className={`text-left p-5 rounded-xl border transition-all duration-200 relative bg-[#111318] ${
                  phase === "verifier" || phase === "healed"
                    ? "border-[#3DFFA2] shadow-[0_0_20px_-5px_rgba(61,255,162,0.3)] ring-1 ring-[#3DFFA2]"
                    : "border-white/[0.08] hover:border-white/[0.15]"
                }`}
              >
                {/* Pod Header */}
                <div className="flex items-center justify-between mb-3 text-xs font-mono">
                  <span className="flex items-center gap-1.5 text-[#3DFFA2] font-semibold">
                    <ShieldCheck className="w-4 h-4" strokeWidth={1.5} />
                    <span>03 // VERIFIER</span>
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#3DFFA2]/10 text-[10px] text-[#3DFFA2]">
                    cgroups-v2
                  </span>
                </div>

                <div className="text-sm font-semibold text-white mb-1.5">
                  Playwright Invariant Gate
                </div>

                <p className="text-xs text-[#9AA0AA] leading-relaxed mb-4">
                  Executes headless Chromium assertions and 36 checkout contracts before rollout.
                </p>

                {/* Invariant Progress Box */}
                <div className="p-3 rounded-lg bg-black/60 border border-white/[0.06] font-mono text-[11px] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[#7C8290]">Invariants Passed:</span>
                    <span className="text-[#3DFFA2] font-bold">{invariantCount} / 36</span>
                  </div>
                  
                  {/* Progress bar using GPU composited scaleX */}
                  <div className="w-full h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#3DFFA2] origin-left transition-transform duration-100"
                      style={{ transform: `scaleX(${invariantCount / 36})` }}
                    />
                  </div>

                  <div className="text-[10px] flex items-center justify-between text-[#9AA0AA]">
                    <span>Receipt Verification</span>
                    <span className={invariantCount === 36 ? "text-[#3DFFA2] font-semibold" : "text-[#7C8290]"}>
                      {invariantCount === 36 ? "ORDER #FL-9942 OK" : "EVALUATING..."}
                    </span>
                  </div>
                </div>

                {/* Pod Bottom Metric */}
                <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-mono text-[#7C8290]">
                  <span>Exit Status</span>
                  <span className={invariantCount === 36 ? "text-[#3DFFA2] font-semibold" : "text-[#7C8290]"}>
                    {invariantCount === 36 ? "Code 0 (Clean)" : "Running..."}
                  </span>
                </div>
              </button>

            </div>

            {/* Selected Agent Deep Inspector Panel */}
            {selectedAgent && AGENTS[selectedAgent] && (
              <div className="p-5 rounded-xl bg-[#111318] border border-white/[0.06] space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.06] pb-3">
                  <div>
                    <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                      <span>{AGENTS[selectedAgent].name}</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-white/[0.05] text-[#2DD4FF] font-mono">
                        {AGENTS[selectedAgent].badge}
                      </span>
                    </h4>
                    <p className="text-xs text-[#9AA0AA]">{AGENTS[selectedAgent].role}</p>
                  </div>

                  <div className="flex items-center gap-4 text-xs font-mono">
                    {AGENTS[selectedAgent].metrics.map((m) => (
                      <div key={m.label} className="flex flex-col sm:items-end">
                        <span className="text-[#7C8290] text-[10px]">{m.label}</span>
                        <span className="text-white font-semibold">{m.value}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="text-xs font-mono text-[#7C8290]">
                  <span className="text-white font-medium">{AGENTS[selectedAgent].outputTitle}:</span>
                  <pre className="mt-2 p-3 rounded-lg bg-black/60 border border-white/[0.04] text-xs text-[#F5F6F8] overflow-x-auto whitespace-pre font-mono">
                    {AGENTS[selectedAgent].outputContent}
                  </pre>
                </div>
              </div>
            )}

            {/* Bottom Status Callout Bar */}
            <div className="p-4 rounded-xl bg-[#111318] border border-white/[0.06] flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-mono">
              <div className="flex items-center gap-3">
                <span className="text-[#7C8290]">CURRENT STATE:</span>
                <span className="text-white font-semibold">
                  {phase === "sentinel" && "500 TypeError detected at checkout.py:43 — dispatching patch request"}
                  {phase === "muse-spark" && "Meta Muse Spark 1.3 generating bounded cast(int, discounts.get(code, 0)) patch"}
                  {phase === "verifier" && "Chromium headless runner asserting 36 checkout contracts and cart invariants"}
                  {phase === "healed" && "FaultLine restored production checkout in 1.14s with 0 dropped orders"}
                </span>
              </div>
              <div className="flex items-center gap-2 text-[#3DFFA2]">
                <span>Zero Human Intervention</span>
                <CheckCircle2 className="w-4 h-4" strokeWidth={1.5} />
              </div>
            </div>

          </div>
        )}

        {/* VIEW 2: SIMULATED PLAYWRIGHT BROWSER VIEWPORT */}
        {activeTab === "browser" && (
          <div className="max-w-3xl mx-auto w-full rounded-2xl border border-white/[0.1] bg-[#0A0B0D] overflow-hidden shadow-2xl relative">
            
            {/* Browser Header Bar */}
            <div className="px-4 py-2.5 bg-[#111318] border-b border-white/[0.08] flex items-center justify-between text-xs font-mono">
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#FF4D6A]" />
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#3DFFA2]" />
                </div>
                <span className="text-[#7C8290] ml-2">Headless Chromium 130</span>
              </div>
              
              <div className="px-4 py-1 rounded-md bg-black/50 border border-white/[0.06] text-[#9AA0AA] text-[11px] flex items-center gap-2 w-72 justify-center">
                <span className="text-[#3DFFA2]">🔒</span>
                <span>http://127.0.0.1:3000/checkout</span>
              </div>

              <div className="text-[10px] text-[#7C8290]">
                Playwright 1.50
              </div>
            </div>

            {/* Browser Simulated Webpage Content */}
            <div className="p-6 sm:p-8 bg-[#0D0F14] min-h-[300px] relative">
              
              {/* Virtual Mouse Pointer using GPU translate3d */}
              <div
                className="absolute z-30 pointer-events-none transition-transform duration-75 ease-out"
                style={{
                  transform: `translate3d(${browserCursor.x * 5.5}px, ${browserCursor.y * 2.2}px, 0)`,
                }}
              >
                <svg
                  className={`w-5 h-5 text-white drop-shadow-md ${browserCursor.clicking ? "scale-90" : "scale-100"}`}
                  viewBox="0 0 24 24"
                  fill="white"
                  stroke="#0A0B0D"
                  strokeWidth="1.5"
                >
                  <path d="M3 3l7 18 3-7 7-3L3 3z" />
                </svg>
                {browserCursor.clicking && (
                  <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-[#2DD4FF] animate-ping" />
                )}
              </div>

              {/* BuggyShop Checkout Card Inside Browser */}
              <div className="max-w-md mx-auto surface-card p-6 rounded-xl border border-white/[0.08] space-y-4 shadow-xl">
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                  <div>
                    <h4 className="text-sm font-semibold text-white">FaultLine BuggyShop</h4>
                    <p className="text-[11px] text-[#9AA0AA]">Order Checkout Review</p>
                  </div>
                  <span className="text-xs font-mono text-[#2DD4FF]">$19.99 USD</span>
                </div>

                <div className="space-y-2 text-xs">
                  <div className="flex items-center justify-between text-[#9AA0AA]">
                    <span>Item: Stainless Steel Camping Mug</span>
                    <span className="text-white">Qty 1</span>
                  </div>
                  <div className="flex items-center justify-between text-[#9AA0AA]">
                    <span>Subtotal:</span>
                    <span className="text-white">$19.99</span>
                  </div>
                  <div className="flex items-center justify-between text-[#9AA0AA]">
                    <span>Coupon:</span>
                    <span className="font-mono text-[#2DD4FF]">TENOFF</span>
                  </div>
                </div>

                {/* State Banner inside Browser */}
                {currentMs < 6800 ? (
                  <div className="p-3 rounded-lg bg-[#FF4D6A]/15 border border-[#FF4D6A]/30 text-xs font-mono text-[#FF4D6A] flex items-center justify-between">
                    <span>500 Internal Server Error</span>
                    <span className="text-[10px]">HEALING VIA AGENT...</span>
                  </div>
                ) : (
                  <div className="p-3 rounded-lg bg-[#3DFFA2]/15 border border-[#3DFFA2]/30 text-xs font-mono text-[#3DFFA2] flex items-center justify-between">
                    <span>Order Confirmed #FL-9942</span>
                    <span className="text-[10px] font-bold">200 OK</span>
                  </div>
                )}

                {/* Simulated Checkout Button */}
                <button
                  type="button"
                  className={`w-full py-2.5 rounded-lg text-xs font-semibold font-mono transition-colors duration-200 ${
                    currentMs < 6800
                      ? "bg-[#FF4D6A] text-white"
                      : "bg-[#3DFFA2] text-[#0A0B0D]"
                  }`}
                >
                  {currentMs < 6800 ? "Checkout Exception (Port 8000)" : "Success • Receipt Dispatched"}
                </button>
              </div>

            </div>

            {/* Browser Bottom Status Footer */}
            <div className="px-4 py-2 bg-[#111318] border-t border-white/[0.06] flex items-center justify-between text-[11px] font-mono text-[#7C8290]">
              <span>DOM Ready: 42ms</span>
              <span className="text-[#3DFFA2]">Assertions: {invariantCount}/36 Green</span>
            </div>

          </div>
        )}

        {/* VIEW 3: NEURAL AST DIFF STREAM */}
        {activeTab === "diff" && (
          <div className="max-w-3xl mx-auto w-full surface-card rounded-2xl border border-white/[0.08] overflow-hidden shadow-2xl bg-[#0A0B0D]">
            
            {/* Diff Header */}
            <div className="px-4 py-3 bg-[#111318] border-b border-white/[0.06] flex items-center justify-between text-xs font-mono">
              <span className="flex items-center gap-2 text-white">
                <Code2 className="w-4 h-4 text-[#2DD4FF]" strokeWidth={1.5} />
                <span>apps/buggyshop-backend/app/routes/checkout.py</span>
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-[#2DD4FF]/10 text-[#2DD4FF] border border-[#2DD4FF]/25">
                Meta Muse Spark 1.3
              </span>
            </div>

            {/* Code Diff Display */}
            <div className="p-5 font-mono text-xs space-y-1.5 bg-[#08090C] overflow-x-auto">
              <div className="text-[#7C8290]">@@ -40,6 +40,7 @@ def apply_discount(payload: CheckoutPayload):</div>
              <div className="text-[#9AA0AA]">   coupon_code = (payload.coupon_code or &quot;&quot;).strip().upper()</div>
              <div className="text-[#9AA0AA]">   discounts: dict[str, int | None] = &#123;&quot;TENOFF&quot;: subtotal // 10&#125;</div>
              
              {/* Deleted line */}
              <div className="flex items-center bg-[#FF4D6A]/15 text-[#FF4D6A] px-2 py-1 rounded">
                <span className="w-5 select-none text-[#FF4D6A]/60">-</span>
                <span>discount = cast(int, discounts.get(coupon_code))</span>
              </div>

              {/* Added line with animated token stream */}
              <div className="flex items-center bg-[#3DFFA2]/15 text-[#3DFFA2] px-2 py-1 rounded">
                <span className="w-5 select-none text-[#3DFFA2]/60">+</span>
                <span>{museTokens || "discount = cast(int, discounts.get(coupon_code, 0))"}</span>
                {phase === "muse-spark" && (
                  <span className="inline-block w-1.5 h-3.5 bg-[#3DFFA2] ml-1" />
                )}
              </div>

              <div className="text-[#9AA0AA]">   total = subtotal - discount</div>
              <div className="text-[#9AA0AA]">   return create_order(namespace, order)</div>
            </div>

            {/* Token Generation Telemetry Bar */}
            <div className="p-3.5 bg-[#111318] border-t border-white/[0.04] text-[11px] font-mono text-[#7C8290] flex flex-wrap items-center justify-between gap-3">
              <span>Prompt Tokens: 38</span>
              <span>Completion Tokens: 14</span>
              <span>Speed: 114 tok/sec</span>
              <span className="text-[#3DFFA2]">AST Firewall: PASS</span>
            </div>

          </div>
        )}

      </div>

    </div>
  );
}
