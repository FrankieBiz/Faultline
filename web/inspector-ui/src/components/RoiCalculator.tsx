"use client";

import React, { useState, useMemo } from "react";
import {
  Calculator,
  TrendingUp,
  Clock,
  ShieldCheck,
  DollarSign,
  Zap,
  Check,
  Copy,
  Sparkles,
} from "lucide-react";

interface RoiCalculatorProps {
  onPlayAudio?: (type: "click" | "success" | "error") => void;
}

export default function RoiCalculator({ onPlayAudio }: RoiCalculatorProps) {
  // Configurable parameters
  const [monthlyOrders, setMonthlyOrders] = useState<number>(85000);
  const [averageOrderValue, setAverageOrderValue] = useState<number>(45);
  const [defectRatePercent, setDefectRatePercent] = useState<number>(0.35); // 0.35% of checkouts hit an unhandled exception
  const [manualMttrHours, setManualMttrHours] = useState<number>(3.5);
  const [engineerHourlyRate, setEngineerHourlyRate] = useState<number>(140);
  const [copiedReport, setCopiedReport] = useState<boolean>(false);

  // Economic calculations
  const metrics = useMemo(() => {
    const annualOrders = monthlyOrders * 12;
    const annualDefectiveOrders = annualOrders * (defectRatePercent / 100);
    const grossRevenueLeakage = annualDefectiveOrders * averageOrderValue;

    // Incidents per year (assuming 1 incident impacts an average batch of carts)
    const annualIncidents = Math.max(12, Math.round(monthlyOrders / 2500));
    const manualTriageHoursAnnual = annualIncidents * manualMttrHours;
    const faultlineTriageHoursAnnual = annualIncidents * (20.4 / 3600); // 20.4 seconds per incident
    const hoursReclaimed = Math.max(0, Math.round(manualTriageHoursAnnual - faultlineTriageHoursAnnual));
    const engineeringSalarySaved = hoursReclaimed * engineerHourlyRate;

    const totalAnnualValue = Math.round(grossRevenueLeakage + engineeringSalarySaved);
    const monthlyValue = Math.round(totalAnnualValue / 12);
    const secondsMttr = 5.6;
    const mttrReductionPct = (((manualMttrHours * 3600 - secondsMttr) / (manualMttrHours * 3600)) * 100).toFixed(1);

    return {
      annualOrders,
      annualDefectiveOrders: Math.round(annualDefectiveOrders),
      grossRevenueLeakage: Math.round(grossRevenueLeakage),
      annualIncidents,
      hoursReclaimed,
      engineeringSalarySaved: Math.round(engineeringSalarySaved),
      totalAnnualValue,
      monthlyValue,
      mttrReductionPct,
    };
  }, [monthlyOrders, averageOrderValue, defectRatePercent, manualMttrHours, engineerHourlyRate]);

  const setPreset = (
    presetOrders: number,
    presetAov: number,
    presetDefect: number,
    presetMttr: number
  ) => {
    if (onPlayAudio) onPlayAudio("click");
    setMonthlyOrders(presetOrders);
    setAverageOrderValue(presetAov);
    setDefectRatePercent(presetDefect);
    setManualMttrHours(presetMttr);
  };

  const handleCopySummary = () => {
    if (onPlayAudio) onPlayAudio("click");
    const summary = `FAULTLINE ECONOMIC VALUE & ROI BRIEF
Analysis Baseline:
- Monthly Checkout Orders: ${monthlyOrders.toLocaleString()}
- Average Order Value (AOV): $${averageOrderValue}
- Unhandled Exception Cart Drop Rate: ${defectRatePercent}%
- Manual MTTR Baseline: ${manualMttrHours} hours vs FaultLine Autonomous: 5.6 seconds

Projected Financial Impact:
- Direct Cart Revenue Preserved: $${metrics.grossRevenueLeakage.toLocaleString()} / year
- Engineering Triage Hours Reclaimed: ${metrics.hoursReclaimed.toLocaleString()} hours / year
- Engineering Salary Reallocated: $${metrics.engineeringSalarySaved.toLocaleString()} / year
- Total Net Annual Value: $${metrics.totalAnnualValue.toLocaleString()} / year ($${metrics.monthlyValue.toLocaleString()} / mo)
- MTTR Acceleration: ${metrics.mttrReductionPct}% reduction with 36/36 AST Invariant Gate`;

    navigator.clipboard.writeText(summary);
    setCopiedReport(true);
    setTimeout(() => setCopiedReport(false), 2000);
  };

  return (
    <section id="roi-calculator" className="py-24 border-t border-white/[0.08] bg-[#0E1015]/40">
      <div className="max-w-[1200px] mx-auto px-6 space-y-12">
        
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
          <div className="space-y-3">
            <div className="text-xs font-mono uppercase tracking-wider text-[#2DD4FF] flex items-center gap-2">
              <Calculator className="w-3.5 h-3.5" />
              <span>Economic Impact Modeling</span>
            </div>
            <h2 className="text-3xl sm:text-4xl font-semibold tracking-[-0.02em] text-[#F5F6F8]">
              Quantify your downtime leakage.
            </h2>
            <p className="text-sm text-[#9AA0AA] max-w-xl">
              See how autonomous AST patch synthesis and ephemeral sandbox verification safeguard your checkout revenue in real-time.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopySummary}
              className="btn-press px-3.5 py-1.5 rounded-lg border border-white/[0.1] hover:border-white/[0.2] bg-white/[0.03] text-xs font-mono text-[#9AA0AA] hover:text-white transition-colors flex items-center gap-1.5"
            >
              {copiedReport ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#3DFFA2]" />
                  <span className="text-[#3DFFA2]">Copied Brief</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-[#2DD4FF]" />
                  <span>Export ROI Brief</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Preset Selector */}
        <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
          <span className="text-[#7C8290] mr-2">Quick Presets:</span>
          <button
            onClick={() => setPreset(25000, 35, 0.25, 2.0)}
            className="px-3 py-1.5 rounded-lg border border-white/[0.08] hover:border-[#2DD4FF]/40 bg-white/[0.02] text-[#9AA0AA] hover:text-white transition-colors"
          >
            Direct-to-Consumer ($1M GMV)
          </button>
          <button
            onClick={() => setPreset(120000, 52, 0.4, 4.0)}
            className="px-3 py-1.5 rounded-lg border border-white/[0.08] hover:border-[#2DD4FF]/40 bg-white/[0.02] text-[#9AA0AA] hover:text-white transition-colors"
          >
            High-Volume Retail ($75M GMV)
          </button>
          <button
            onClick={() => setPreset(450000, 78, 0.5, 5.5)}
            className="px-3 py-1.5 rounded-lg border border-white/[0.08] hover:border-[#2DD4FF]/40 bg-white/[0.02] text-[#9AA0AA] hover:text-white transition-colors"
          >
            Enterprise Marketplace ($400M GMV)
          </button>
        </div>

        {/* Main Calculator Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          
          {/* Controls Column (7 cols) */}
          <div className="lg:col-span-7 surface-card p-6 sm:p-8 space-y-6">
            <div className="flex items-center justify-between pb-4 border-b border-white/[0.06]">
              <span className="text-xs font-mono uppercase tracking-wider text-[#F5F6F8] font-semibold">
                Storefront & Operational Parameters
              </span>
              <span className="text-[11px] font-mono text-[#7C8290]">
                Live Reactive Model
              </span>
            </div>

            {/* Slider 1: Monthly Orders */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#9AA0AA]">Monthly Checkout Transactions</span>
                <span className="font-mono text-[#F5F6F8] font-semibold">
                  {monthlyOrders.toLocaleString()} orders
                </span>
              </div>
              <input
                type="range"
                min="5000"
                max="500000"
                step="5000"
                value={monthlyOrders}
                onChange={(e) => setMonthlyOrders(Number(e.target.value))}
                className="w-full accent-[#2DD4FF] cursor-pointer"
              />
              <div className="flex justify-between text-[10px] font-mono text-[#7C8290]">
                <span>5,000 / mo</span>
                <span>250,000</span>
                <span>500,000 / mo</span>
              </div>
            </div>

            {/* Slider 2: Average Order Value */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#9AA0AA]">Average Order Value (AOV)</span>
                <span className="font-mono text-[#F5F6F8] font-semibold">
                  ${averageOrderValue} USD
                </span>
              </div>
              <input
                type="range"
                min="15"
                max="250"
                step="5"
                value={averageOrderValue}
                onChange={(e) => setAverageOrderValue(Number(e.target.value))}
                className="w-full accent-[#2DD4FF] cursor-pointer"
              />
              <div className="flex justify-between text-[10px] font-mono text-[#7C8290]">
                <span>$15</span>
                <span>$125</span>
                <span>$250</span>
              </div>
            </div>

            {/* Slider 3: Unhandled Defect Rate */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#9AA0AA]">Unhandled Edge-Case Exception Rate</span>
                <span className="font-mono text-[#FF4D6A] font-semibold">
                  {defectRatePercent.toFixed(2)}%
                </span>
              </div>
              <input
                type="range"
                min="0.05"
                max="1.50"
                step="0.05"
                value={defectRatePercent}
                onChange={(e) => setDefectRatePercent(Number(e.target.value))}
                className="w-full accent-[#FF4D6A] cursor-pointer"
              />
              <div className="flex justify-between text-[10px] font-mono text-[#7C8290]">
                <span>0.05% (Elite)</span>
                <span>0.75%</span>
                <span>1.50% (High Toil)</span>
              </div>
            </div>

            {/* Grid 2 Sliders: MTTR & Engineer Rate */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
              <div className="space-y-2 p-3.5 rounded-xl bg-black/40 border border-white/[0.04]">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[#9AA0AA]">Manual MTTR</span>
                  <span className="font-mono text-amber-400 font-semibold">{manualMttrHours} hrs</span>
                </div>
                <input
                  type="range"
                  min="0.5"
                  max="8.0"
                  step="0.5"
                  value={manualMttrHours}
                  onChange={(e) => setManualMttrHours(Number(e.target.value))}
                  className="w-full accent-amber-400 cursor-pointer"
                />
              </div>

              <div className="space-y-2 p-3.5 rounded-xl bg-black/40 border border-white/[0.04]">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[#9AA0AA]">SRE Hourly Rate</span>
                  <span className="font-mono text-[#3DFFA2] font-semibold">${engineerHourlyRate}/hr</span>
                </div>
                <input
                  type="range"
                  min="80"
                  max="250"
                  step="10"
                  value={engineerHourlyRate}
                  onChange={(e) => setEngineerHourlyRate(Number(e.target.value))}
                  className="w-full accent-[#3DFFA2] cursor-pointer"
                />
              </div>
            </div>
          </div>

          {/* KPI Output Column (5 cols) */}
          <div className="lg:col-span-5 space-y-4">
            
            {/* Primary Value Card */}
            <div className="p-6 rounded-2xl bg-gradient-to-b from-[#2DD4FF]/15 to-[#0E1015] border border-[#2DD4FF]/40 shadow-[0_0_35px_-5px_rgba(45,212,255,0.25)] space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono uppercase tracking-wider text-[#2DD4FF]">
                  Projected Annual Value
                </span>
                <span className="px-2 py-0.5 rounded-full bg-[#2DD4FF]/20 text-[#2DD4FF] text-[10px] font-mono">
                  Guaranteed ROI
                </span>
              </div>

              <div className="text-4xl sm:text-5xl font-mono font-bold text-white tracking-tight">
                ${metrics.totalAnnualValue.toLocaleString()}
              </div>

              <p className="text-xs text-[#9AA0AA] leading-relaxed">
                Recovered across <span className="text-white font-medium">{metrics.annualDefectiveOrders.toLocaleString()} dropped carts</span> and <span className="text-white font-medium">{metrics.hoursReclaimed} engineering hours</span> annually.
              </p>

              <div className="pt-3 border-t border-white/[0.1] flex items-center justify-between text-xs font-mono">
                <span className="text-[#7C8290]">Monthly Preserved</span>
                <span className="text-[#3DFFA2] font-semibold">+${metrics.monthlyValue.toLocaleString()} / mo</span>
              </div>
            </div>

            {/* Breakdown Subcards */}
            <div className="grid grid-cols-2 gap-3">
              <div className="p-4 rounded-xl bg-[#111318] border border-white/[0.08] space-y-1">
                <div className="text-[11px] font-mono text-[#7C8290] flex items-center gap-1.5">
                  <DollarSign className="w-3.5 h-3.5 text-[#3DFFA2]" />
                  <span>Cart Revenue</span>
                </div>
                <div className="text-lg font-mono font-semibold text-[#F5F6F8]">
                  ${metrics.grossRevenueLeakage.toLocaleString()}
                </div>
                <p className="text-[10px] text-[#9AA0AA]">Direct margin saved</p>
              </div>

              <div className="p-4 rounded-xl bg-[#111318] border border-white/[0.08] space-y-1">
                <div className="text-[11px] font-mono text-[#7C8290] flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-purple-400" />
                  <span>MTTR Accelerated</span>
                </div>
                <div className="text-lg font-mono font-semibold text-[#2DD4FF]">
                  {metrics.mttrReductionPct}%
                </div>
                <p className="text-[10px] text-[#9AA0AA]">From {manualMttrHours}h to 5.6s</p>
              </div>
            </div>

            {/* Enterprise Security Assurances */}
            <div className="p-4 rounded-xl bg-[#111318]/60 border border-white/[0.06] space-y-2">
              <div className="text-xs font-semibold text-white flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-[#3DFFA2]" />
                <span>Zero-Trust Production Safeguards</span>
              </div>
              <ul className="text-[11px] text-[#9AA0AA] space-y-1 font-mono">
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#3DFFA2]" />
                  <span>36 Deterministic AST Invariants verify candidate hotfixes</span>
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#3DFFA2]" />
                  <span>Disposable git worktrees guarantee zero runtime contamination</span>
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#3DFFA2]" />
                  <span>Atomic lease locking prevents concurrent patch collisions</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
