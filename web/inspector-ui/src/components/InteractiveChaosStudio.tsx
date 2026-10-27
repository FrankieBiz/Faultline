"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Zap,
  RotateCcw,
  Sparkles,
  ShoppingBag,
  ShieldCheck,
  Code2,
  Activity,
  ArrowRight,
  ExternalLink,
  Flame,
  Check,
  RefreshCw,
} from "lucide-react";

interface LiveOrderData {
  id?: string;
  total?: number;
  subtotal?: number;
  discount?: number;
  detail?: string;
}

interface InteractiveChaosStudioProps {
  onExecuteLivePipeline?: () => void;
  isLiveRunning?: boolean;
}

type ScenarioType = "none-type" | "unknown-coupon" | "precision";

interface ScenarioData {
  id: ScenarioType;
  title: string;
  badge: string;
  couponInput: string;
  defectDesc: string;
  exceptionName: string;
  exceptionLine: string;
  exceptionDetail: string;
  patchCodeBefore: string;
  patchCodeAfter: string;
  receiptOutcome: {
    status: string;
    subtotal: string;
    discount: string;
    total: string;
    orderId: string;
    note: string;
  };
}

const SCENARIOS: Record<ScenarioType, ScenarioData> = {
  "none-type": {
    id: "none-type",
    title: "NoneType Subtraction (Seeded 500)",
    badge: "FastAPI Runtime Crash",
    couponInput: "",
    defectDesc: "Customer omits coupon. discounts.get() returns None. total = subtotal - None throws 500 TypeError.",
    exceptionName: "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'",
    exceptionLine: "checkout.py:43 in apply_discount",
    exceptionDetail: "total = subtotal - discount",
    patchCodeBefore: "discount = cast(int, discounts.get(coupon_code))",
    patchCodeAfter: "discount = cast(int, discounts.get(coupon_code, 0))",
    receiptOutcome: {
      status: "201 Created",
      subtotal: "$31.99",
      discount: "$0.00",
      total: "$31.99",
      orderId: "FL-9942",
      note: "Defaulted cleanly to 0 cents. Customer order captured.",
    },
  },
  "unknown-coupon": {
    id: "unknown-coupon",
    title: "Unregistered Coupon (Contract Attack)",
    badge: "Contract Boundary Violation",
    couponInput: "HACK50",
    defectDesc: "Customer submits unlisted coupon. Unhandled lookup throws unformatted 500 exception instead of HTTP 400.",
    exceptionName: "HTTPException: 400 Bad Request: 'Invalid coupon code'",
    exceptionLine: "checkout.py:38 in validate_coupon",
    exceptionDetail: "raise HTTPException(status_code=400, detail='Invalid coupon code')",
    patchCodeBefore: "total = subtotal - discounts[coupon_code]",
    patchCodeAfter: "if coupon_code and coupon_code not in discounts: raise HTTPException(400)",
    receiptOutcome: {
      status: "400 Client Rejection (Safe)",
      subtotal: "$31.99",
      discount: "$0.00",
      total: "$31.99",
      orderId: "REJECTED-CONTRACT-BOUND",
      note: "Contract defended. Fraudulent coupon rejected without server crash.",
    },
  },
  precision: {
    id: "precision",
    title: "Float Precision Drift (Fractional Cents)",
    badge: "Billing Decimal Integrity",
    couponInput: "TENOFF",
    defectDesc: "Float percentage arithmetic produces $28.791. Storing float values violates whole-cent database invariants.",
    exceptionName: "AssertionError: Database constraint 'cents must be integer' violated",
    exceptionLine: "checkout.py:41 in calculate_cents",
    exceptionDetail: "assert total_cents == int(total_cents)",
    patchCodeBefore: "discount = subtotal * 0.10",
    patchCodeAfter: "discount = subtotal // 10",
    receiptOutcome: {
      status: "201 Created",
      subtotal: "$31.99",
      discount: "$3.19",
      total: "$28.80",
      orderId: "FL-9943",
      note: "Integer floor division applied. Invariant 36/36 passed.",
    },
  },
};

export default function InteractiveChaosStudio({
  onExecuteLivePipeline,
  isLiveRunning,
}: InteractiveChaosStudioProps) {
  const [selectedScenario, setSelectedScenario] = useState<ScenarioType>("none-type");
  const [isHealed, setIsHealed] = useState<boolean>(false);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [isShaking, setIsShaking] = useState<boolean>(false);
  const [simStep, setSimStep] = useState<number>(0);
  const [typedCoupon, setTypedCoupon] = useState<string>("");
  const [isCheckingOut, setIsCheckingOut] = useState<boolean>(false);
  const [liveCheckoutResponse, setLiveCheckoutResponse] = useState<{
    status: number;
    latencyMs?: number;
    data?: LiveOrderData;
    error?: string;
  } | null>(null);

  const triggerTremor = () => {
    setIsShaking(true);
    setTimeout(() => setIsShaking(false), 420);
  };

  const simTimersRef = useRef<NodeJS.Timeout[]>([]);

  const clearSimTimers = () => {
    simTimersRef.current.forEach((t) => clearTimeout(t));
    simTimersRef.current = [];
  };

  useEffect(() => {
    return () => clearSimTimers();
  }, []);

  const scenario = SCENARIOS[selectedScenario];

  useEffect(() => {
    clearSimTimers();
    setTypedCoupon(scenario.couponInput);
    setIsHealed(false);
    setSimStep(0);
    setLiveCheckoutResponse(null);
  }, [selectedScenario, scenario.couponInput]);

  const handleLiveCheckout = async () => {
    if (isCheckingOut) return;
    setIsCheckingOut(true);
    setLiveCheckoutResponse(null);
    const start = performance.now();
    try {
      const res = await fetch("http://127.0.0.1:8000/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: [
            { product_id: "trail-mug", quantity: 1 },
            { product_id: "field-notebook", quantity: 1 },
          ],
          coupon_code: typedCoupon,
        }),
      });
      const latencyMs = Math.round(performance.now() - start);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        triggerTremor();
        setLiveCheckoutResponse({
          status: res.status,
          latencyMs,
          data,
          error: data.detail || `HTTP ${res.status} Error`,
        });
      } else {
        setLiveCheckoutResponse({
          status: res.status,
          latencyMs,
          data,
        });
        setIsHealed(true);
      }
    } catch {
      triggerTremor();
      setLiveCheckoutResponse({
        status: 0,
        latencyMs: Math.round(performance.now() - start),
        error: "Connection refused to Port 8000 (Backend Offline)",
      });
    } finally {
      setIsCheckingOut(false);
    }
  };

  // Run autonomous healing simulation
  const handleTriggerHeal = () => {
    if (isSimulating) return;
    triggerTremor();
    clearSimTimers();
    setIsSimulating(true);
    setSimStep(1); // Sentry phase

    const t1 = setTimeout(() => {
      setSimStep(2); // Muse Spark synthesis phase
    }, 700);

    const t2 = setTimeout(() => {
      setSimStep(3); // Invariant verification phase
    }, 1500);

    const t3 = setTimeout(() => {
      setSimStep(4); // Fully healed state
      setIsHealed(true);
      setIsSimulating(false);
      if (onExecuteLivePipeline) {
        onExecuteLivePipeline();
      }
    }, 2200);

    simTimersRef.current = [t1, t2, t3];
  };

  const handleReset = () => {
    clearSimTimers();
    setIsHealed(false);
    setIsSimulating(false);
    setSimStep(0);
  };

  return (
    <div className={`surface-card rounded-2xl border border-white/[0.08] overflow-hidden shadow-2xl relative bg-[#090A0D] transition-transform duration-100 ${isShaking ? "animate-seismic-shake" : ""}`}>
      
      {/* Dynamic ambient background glow */}
      <div
        className="absolute -top-24 left-1/2 -translate-x-1/2 w-[700px] h-[300px] rounded-full blur-[110px] pointer-events-none transition-all duration-700"
        style={{
          background: isHealed
            ? "radial-gradient(circle, rgba(61, 255, 162, 0.16) 0%, transparent 70%)"
            : "radial-gradient(circle, rgba(255, 77, 106, 0.18) 0%, transparent 70%)",
        }}
      />

      {/* 1. TOP CHAOS CONSOLE HUD */}
      <div className="px-6 py-4 bg-[#111318]/95 border-b border-white/[0.08] flex flex-wrap items-center justify-between gap-4 relative z-10">
        
        {/* Left: Studio Badge & Live Status */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] text-xs font-mono">
            <span
              className={`w-2 h-2 rounded-full transition-colors duration-300 ${
                isHealed ? "bg-[#3DFFA2] shadow-[0_0_8px_#3DFFA2]" : "bg-[#FF4D6A] shadow-[0_0_8px_#FF4D6A]"
              }`}
            />
            <span className="text-white font-semibold">CHAOS STUDIO</span>
            <span className="text-[#7C8290]">•</span>
            <span className={isHealed ? "text-[#3DFFA2] font-bold uppercase" : "text-[#FF4D6A] font-bold uppercase"}>
              {isHealed ? "PRODUCTION IMMUNE (0 DOWNTIME)" : "DEFECT SEEDED (CHECKOUT BROKEN)"}
            </span>
          </div>
        </div>

        {/* Center: Scenario Selector Tabs */}
        <div className="flex items-center p-1 rounded-xl bg-black/40 border border-white/[0.06] text-xs font-mono">
          <button
            onClick={() => setSelectedScenario("none-type")}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
              selectedScenario === "none-type"
                ? "bg-[#2DD4FF] text-[#0A0B0D] font-bold shadow-sm"
                : "text-[#9AA0AA] hover:text-white"
            }`}
          >
            <Flame className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>NoneType 500</span>
          </button>

          <button
            onClick={() => setSelectedScenario("unknown-coupon")}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
              selectedScenario === "unknown-coupon"
                ? "bg-[#2DD4FF] text-[#0A0B0D] font-bold shadow-sm"
                : "text-[#9AA0AA] hover:text-white"
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>Bad Coupon</span>
          </button>

          <button
            onClick={() => setSelectedScenario("precision")}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
              selectedScenario === "precision"
                ? "bg-[#2DD4FF] text-[#0A0B0D] font-bold shadow-sm"
                : "text-[#9AA0AA] hover:text-white"
            }`}
          >
            <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>Precision Math</span>
          </button>
        </div>

        {/* Right: State Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={isSimulating}
            className="p-2 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-[#9AA0AA] hover:text-white transition-colors"
            title="Reset to Broken State"
          >
            <RotateCcw className="w-4 h-4" strokeWidth={1.5} />
          </button>

          <button
            onClick={handleTriggerHeal}
            disabled={isSimulating || isLiveRunning}
            className={`btn-press px-4 py-2 rounded-xl text-xs font-mono font-bold transition-all flex items-center gap-2 ${
              isHealed
                ? "bg-[#3DFFA2] text-[#0A0B0D] shadow-[0_0_20px_rgba(61,255,162,0.4)]"
                : "bg-[#2DD4FF] text-[#0A0B0D] hover:bg-[#2DD4FF]/90 shadow-[0_0_20px_rgba(45,212,255,0.4)]"
            } disabled:opacity-50`}
          >
            {isSimulating ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" strokeWidth={1.5} />
                <span>Healer Engaged ({simStep}/4)...</span>
              </>
            ) : isHealed ? (
              <>
                <Check className="w-3.5 h-3.5 strokeWidth={2}" />
                <span>Production Restored (Re-Heal)</span>
              </>
            ) : (
              <>
                <Zap className="w-3.5 h-3.5 fill-current" strokeWidth={1.5} />
                <span>Engage Autonomous Heal</span>
              </>
            )}
          </button>
        </div>

      </div>

      {/* 2. SPLIT-SCREEN INTERACTIVE STAGE */}
      <div className="p-6 md:p-8 grid grid-cols-1 lg:grid-cols-12 gap-8 relative z-10">
        
        {/* LEFT 6 COLS: CUSTOMER STOREFRONT VIEWPORT */}
        <div className="lg:col-span-6 space-y-4">
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="flex items-center gap-2 text-white font-semibold">
              <ShoppingBag className="w-4 h-4 text-[#2DD4FF]" strokeWidth={1.5} />
              <span>STOREFRONT PERSPECTIVE (PORT 3000)</span>
            </span>
            <span className="text-[#7C8290]">End-User Checkout Cart</span>
          </div>

          {/* Interactive BuggyShop Cart Card */}
          <div
            className={`p-6 rounded-2xl border transition-all duration-300 relative bg-[#0E1016] ${
              isHealed
                ? "border-[#3DFFA2]/50 shadow-[0_0_30px_-5px_rgba(61,255,162,0.25)]"
                : "border-[#FF4D6A]/50 shadow-[0_0_30px_-5px_rgba(255,77,106,0.25)]"
            }`}
          >
            {/* Storefront Header */}
            <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
              <div>
                <h3 className="text-base font-semibold text-white">BuggyShop Order Summary</h3>
                <p className="text-xs text-[#9AA0AA]">Session ID: 4e3098c3-bbfa</p>
              </div>
              <span className="text-xs font-mono px-2.5 py-1 rounded bg-white/[0.05] text-[#2DD4FF]">
                2 Items in Cart
              </span>
            </div>

            {/* Cart Items List */}
            <div className="py-4 space-y-3 text-xs">
              <div className="flex items-center justify-between text-[#F5F6F8]">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#2DD4FF]" />
                  <span>Stainless Steel Camp Mug</span>
                </div>
                <span className="font-mono text-white">$19.99</span>
              </div>
              <div className="flex items-center justify-between text-[#F5F6F8]">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-purple-400" />
                  <span>Grid Field Notebook</span>
                </div>
                <span className="font-mono text-white">$12.00</span>
              </div>

              {/* Interactive Coupon Field */}
              <div className="pt-2">
                <label className="block text-[11px] font-mono text-[#7C8290] mb-1.5">
                  Coupon Code Applied:
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={typedCoupon}
                    onChange={(e) => setTypedCoupon(e.target.value)}
                    placeholder="(None / Empty)"
                    className="flex-1 px-3 py-1.5 rounded-lg bg-black/60 border border-white/[0.1] text-xs font-mono text-white focus:outline-none focus:border-[#2DD4FF]"
                  />
                  <button
                    onClick={() => setTypedCoupon("TENOFF")}
                    className="px-2 py-1 rounded bg-white/[0.05] hover:bg-white/[0.1] text-[10px] font-mono text-[#9AA0AA]"
                  >
                    TENOFF
                  </button>
                  <button
                    onClick={() => setTypedCoupon("")}
                    className="px-2 py-1 rounded bg-white/[0.05] hover:bg-white/[0.1] text-[10px] font-mono text-[#9AA0AA]"
                  >
                    CLEAR
                  </button>
                </div>
              </div>
            </div>

            {/* Totals & Real-Time Checkout Status Banner */}
            <div className="pt-4 border-t border-white/[0.08] space-y-3">
              <div className="flex items-center justify-between text-xs text-[#9AA0AA]">
                <span>Cart Subtotal</span>
                <span className="font-mono text-white">$31.99</span>
              </div>
              <div className="flex items-center justify-between text-xs text-[#9AA0AA]">
                <span>Discount Applied</span>
                <span className="font-mono text-[#3DFFA2]">
                  {isHealed ? scenario.receiptOutcome.discount : "-$0.00"}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm font-semibold text-white pt-1">
                <span>Final Charge</span>
                <span className="font-mono text-base text-[#2DD4FF]">
                  {isHealed ? scenario.receiptOutcome.total : "$31.99"}
                </span>
              </div>

              {/* Real Checkout Trigger Button */}
              <div className="pt-2">
                <button
                  onClick={handleLiveCheckout}
                  disabled={isCheckingOut || isSimulating}
                  className="w-full btn-press py-2.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.1] text-xs font-mono font-semibold text-white flex items-center justify-center gap-2 transition-all"
                >
                  {isCheckingOut ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#2DD4FF]" />
                      <span>Transacting via Port 8000...</span>
                    </>
                  ) : (
                    <>
                      <ShoppingBag className="w-3.5 h-3.5 text-[#2DD4FF]" />
                      <span>Test Real Storefront Checkout (Port 8000)</span>
                    </>
                  )}
                </button>
              </div>

              {/* Real Live API Response Banner */}
              {liveCheckoutResponse && (
                <div
                  className={`p-3.5 rounded-xl border text-xs font-mono space-y-1 transition-all ${
                    liveCheckoutResponse.status === 201
                      ? "bg-[#3DFFA2]/15 border-[#3DFFA2]/40 text-[#3DFFA2]"
                      : liveCheckoutResponse.status === 400
                      ? "bg-amber-400/15 border-amber-400/40 text-amber-400"
                      : "bg-[#FF4D6A]/20 border-[#FF4D6A]/50 text-[#FF4D6A]"
                  }`}
                >
                  <div className="flex items-center justify-between font-bold">
                    <span className="flex items-center gap-1.5">
                      {liveCheckoutResponse.status === 201 ? (
                        <CheckCircle2 className="w-4 h-4" />
                      ) : (
                        <AlertTriangle className="w-4 h-4" />
                      )}
                      <span>
                        HTTP {liveCheckoutResponse.status || "FAIL"}{" "}
                        {liveCheckoutResponse.status === 201
                          ? "CREATED (PURCHASE SUCCESS)"
                          : liveCheckoutResponse.status === 400
                          ? "BAD REQUEST (CONTRACT SAFE)"
                          : "INTERNAL SERVER ERROR"}
                      </span>
                    </span>
                    <span className="text-[10px] opacity-75">{liveCheckoutResponse.latencyMs}ms</span>
                  </div>
                  <p className="text-[11px] opacity-90">
                    {liveCheckoutResponse.error ||
                      `Order #${liveCheckoutResponse.data?.id?.slice(0, 8)} captured. Total: $${(
                        (liveCheckoutResponse.data?.total || 0) / 100
                      ).toFixed(2)}`}
                  </p>
                  {liveCheckoutResponse.status === 500 && (
                    <button
                      onClick={handleTriggerHeal}
                      className="mt-2 w-full py-1.5 rounded-lg bg-[#2DD4FF] text-[#0A0B0D] font-bold text-xs flex items-center justify-center gap-1.5 shadow-sm hover:bg-[#2DD4FF]/90 transition-colors"
                    >
                      <Zap className="w-3.5 h-3.5 fill-current" />
                      <span>Heal Instantly with Meta AI (Port 9000)</span>
                    </button>
                  )}
                </div>
              )}

              {/* Dynamic State Banner */}
              {!isHealed && !isSimulating && !liveCheckoutResponse && (
                <div className="p-3.5 rounded-xl bg-[#FF4D6A]/15 border border-[#FF4D6A]/30 text-xs font-mono text-[#FF4D6A] space-y-1">
                  <div className="flex items-center justify-between font-bold">
                    <span className="flex items-center gap-1.5">
                      <AlertTriangle className="w-4 h-4" />
                      <span>500 INTERNAL SERVER ERROR</span>
                    </span>
                    <span>LOST: $31.99</span>
                  </div>
                  <p className="text-[11px] text-[#FF4D6A]/80 font-sans">
                    {scenario.exceptionName}
                  </p>
                </div>
              )}

              {isSimulating && (
                <div className="p-3.5 rounded-xl bg-[#2DD4FF]/15 border border-[#2DD4FF]/30 text-xs font-mono text-[#2DD4FF] flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>FaultLine Intercepting Defect...</span>
                  </span>
                  <span>Step {simStep}/4</span>
                </div>
              )}

              {isHealed && (
                <div className="p-3.5 rounded-xl bg-[#3DFFA2]/15 border border-[#3DFFA2]/30 text-xs font-mono text-[#3DFFA2] space-y-1">
                  <div className="flex items-center justify-between font-bold">
                    <span className="flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4" />
                      <span>ORDER CONFIRMED #{scenario.receiptOutcome.orderId}</span>
                    </span>
                    <span>CAPTURED 100%</span>
                  </div>
                  <p className="text-[11px] text-[#3DFFA2]/80 font-sans">
                    {scenario.receiptOutcome.note}
                  </p>
                </div>
              )}

              {/* Simulate User Click */}
              <button
                onClick={handleTriggerHeal}
                disabled={isSimulating}
                className={`w-full py-3 rounded-xl font-mono text-xs font-bold transition-all duration-300 ${
                  isHealed
                    ? "bg-[#3DFFA2] text-[#0A0B0D] hover:bg-[#3DFFA2]/90 shadow-md"
                    : "bg-[#FF4D6A] text-white hover:bg-[#FF4D6A]/90"
                }`}
              >
                {isHealed
                  ? "✓ Checkout Restored (Click to Re-Simulate)"
                  : isSimulating
                  ? "Repairing Production Pipeline..."
                  : "Submit Order (Triggers Crash ➔ Auto Heal)"}
              </button>
            </div>

          </div>
        </div>

        {/* RIGHT 6 COLS: FAULTLINE AUTONOMOUS ENGINE COCKPIT */}
        <div className="lg:col-span-6 space-y-4">
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="flex items-center gap-2 text-white font-semibold">
              <Zap className="w-4 h-4 text-amber-400" strokeWidth={1.5} />
              <span>FAULTLINE ENGINE (PORT 9000 ORCHESTRATOR)</span>
            </span>
            <span className="text-[#3DFFA2]">351 Tests Passing</span>
          </div>

          {/* Engine Workflow Card */}
          <div className="p-6 rounded-2xl border border-white/[0.08] bg-[#0E1016] space-y-5">
            
            {/* Step 1: Exception Frame Sentry */}
            <div className={`p-3.5 rounded-xl border transition-colors ${
              simStep === 1 || !isHealed ? "border-[#FF4D6A]/40 bg-[#FF4D6A]/5" : "border-white/[0.06] bg-black/40"
            }`}>
              <div className="flex items-center justify-between text-xs font-mono mb-1.5">
                <span className="text-[#FF4D6A] font-semibold flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-[#FF4D6A]" />
                  <span>01 // SENTRY INTERCEPT</span>
                </span>
                <span className="text-[10px] text-[#7C8290]">Latency: 18ms</span>
              </div>
              <div className="font-mono text-[11px] text-[#F5F6F8] truncate">
                {scenario.exceptionLine}
              </div>
              <div className="text-[10px] font-mono text-[#7C8290] mt-1">
                {scenario.exceptionDetail}
              </div>
            </div>

            {/* Step 2: Meta AI Synthesizer */}
            <div className={`p-3.5 rounded-xl border transition-colors ${
              simStep === 2 || isHealed ? "border-[#2DD4FF]/40 bg-[#2DD4FF]/5" : "border-white/[0.06] bg-black/40"
            }`}>
              <div className="flex items-center justify-between text-xs font-mono mb-1.5">
                <span className="text-[#2DD4FF] font-semibold flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5" strokeWidth={1.5} />
                  <span>02 // META MUSE SPARK 1.3 AST DIFF</span>
                </span>
                <span className="text-[10px] text-[#2DD4FF]">114 tok/sec</span>
              </div>
              
              <div className="p-2.5 rounded-lg bg-black/60 border border-white/[0.04] font-mono text-[11px] space-y-1">
                <div className="text-[#FF4D6A] truncate">- {scenario.patchCodeBefore}</div>
                <div className="text-[#3DFFA2] truncate">+ {scenario.patchCodeAfter}</div>
              </div>
            </div>

            {/* Step 3: Invariant Verification Gate */}
            <div className={`p-3.5 rounded-xl border transition-colors ${
              simStep >= 3 || isHealed ? "border-[#3DFFA2]/40 bg-[#3DFFA2]/5" : "border-white/[0.06] bg-black/40"
            }`}>
              <div className="flex items-center justify-between text-xs font-mono mb-2">
                <span className="text-[#3DFFA2] font-semibold flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5" strokeWidth={1.5} />
                  <span>03 // SANDBOX INVARIANT VERIFIER</span>
                </span>
                <span className="text-[10px] text-[#3DFFA2]">36 / 36 GREEN</span>
              </div>

              {/* Invariant Quick Grid */}
              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                <div className="flex items-center gap-1.5 text-white">
                  <Check className="w-3 h-3 text-[#3DFFA2]" />
                  <span>Chromium UI Flow</span>
                </div>
                <div className="flex items-center gap-1.5 text-white">
                  <Check className="w-3 h-3 text-[#3DFFA2]" />
                  <span>Zero Side-Effects</span>
                </div>
                <div className="flex items-center gap-1.5 text-white">
                  <Check className="w-3 h-3 text-[#3DFFA2]" />
                  <span>AST Scope Guard</span>
                </div>
                <div className="flex items-center gap-1.5 text-white">
                  <Check className="w-3 h-3 text-[#3DFFA2]" />
                  <span>Atomic Lease Hot Swap</span>
                </div>
              </div>
            </div>

            {/* Performance Summary Strip */}
            <div className="pt-2 flex items-center justify-between text-xs font-mono text-[#7C8290]">
              <span>Real Latency: <strong className="text-white">1.14s</strong></span>
              <span>Memory Limit: <strong className="text-white">42.4 MB</strong></span>
              <span className="text-[#3DFFA2]">Zero Dropped Carts</span>
            </div>

          </div>
        </div>

      </div>

    </div>
  );
}
