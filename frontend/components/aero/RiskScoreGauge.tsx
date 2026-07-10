"use client";
import { useEffect, useRef, useState } from "react";

// Sub-metrics shown below the dial
const SUB_METRICS = [
  { label: "Sharpe",      value: 1.24, max: 3,   unit: "",  color: "#00FF88" },
  { label: "Sortino",     value: 1.87, max: 4,   unit: "",  color: "#00FF88" },
  { label: "Calmar",      value: 0.91, max: 2,   unit: "",  color: "#FFB800" },
  { label: "Max DD",      value: 11.2, max: 30,  unit: "%", color: "#FFB800" },
  { label: "Correlation", value: 0.23, max: 1,   unit: "",  color: "#00FF88" },
  { label: "Volatility",  value: 14.7, max: 50,  unit: "%", color: "#00FF88" },
];

const SCORE = 82; // out of 100

export function RiskScoreGauge({ active }: { active: boolean }) {
  const [animScore, setAnimScore] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      setAnimScore(0);
      startRef.current = null;
      return;
    }
    const DURATION = 1600;
    const animate = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const t = Math.min((now - startRef.current) / DURATION, 1);
      // ease-out-cubic
      const eased = 1 - Math.pow(1 - t, 3);
      setAnimScore(Math.round(eased * SCORE));
      if (t < 1) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [active]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="t-label">RISK ASSESSMENT</span>
        {active && (
          <span className="text-[10px] font-mono animate-pulse flex items-center gap-1" style={{ color: "var(--t-cyan)" }}>
            <span className="w-1.5 h-1.5 inline-block" style={{ background: "var(--t-cyan)" }} />
            COMPUTING
          </span>
        )}
      </div>

      <div className="flex flex-col sm:flex-row items-center gap-6">
        <GaugeDial score={animScore} />
        <SubMetricGrid score={animScore} />
      </div>
    </div>
  );
}

// ── Dial ──────────────────────────────────────────────────────────────────────

function GaugeDial({ score }: { score: number }) {
  // SVG arc params
  const R = 70;
  const CX = 90, CY = 90;
  const START_DEG = 210; // arc starts at lower-left
  const END_DEG = -30;   // arc ends at lower-right → 240° sweep
  const SWEEP = 240;

  // Convert degrees to radians, origin top = 0 going clockwise
  const toRad = (deg: number) => ((deg - 90) * Math.PI) / 180;

  const arcPoint = (deg: number) => ({
    x: CX + R * Math.cos(toRad(deg)),
    y: CY + R * Math.sin(toRad(deg)),
  });

  // Arc path helper
  const describeArc = (startDeg: number, sweepDeg: number) => {
    const s = arcPoint(startDeg);
    const eDeg = startDeg + sweepDeg;
    const e = arcPoint(eDeg);
    const largeArc = sweepDeg > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${R} ${R} 0 ${largeArc} 1 ${e.x} ${e.y}`;
  };

  // Filled portion based on score (0–100 mapped to SWEEP degrees)
  const filledSweep = (score / 100) * SWEEP;

  // Needle angle: START_DEG + filledSweep
  const needleDeg = START_DEG + filledSweep;
  const needleLen = R - 10;
  const needleTip = arcPoint(needleDeg);
  // Needle base is slightly offset from center
  const needleBase1 = {
    x: CX + 6 * Math.cos(toRad(needleDeg + 90)),
    y: CY + 6 * Math.sin(toRad(needleDeg + 90)),
  };
  const needleBase2 = {
    x: CX + 6 * Math.cos(toRad(needleDeg - 90)),
    y: CY + 6 * Math.sin(toRad(needleDeg - 90)),
  };

  // Zone colors along the track (red → yellow → green)
  const scoreColor = score >= 75 ? "#00FF88" : score >= 50 ? "#FFB800" : "#FF3B5C";
  const grade = score >= 75 ? "A" : score >= 60 ? "B" : score >= 45 ? "C" : "D";
  const gradeLabel = score >= 75 ? "LOW RISK" : score >= 60 ? "MODERATE" : score >= 45 ? "ELEVATED" : "HIGH RISK";

  return (
    <div className="relative flex-shrink-0">
      <svg width="180" height="130" viewBox="0 0 180 130">
        {/* Track background */}
        <path
          d={describeArc(START_DEG, SWEEP)}
          fill="none"
          stroke="#1e293b"
          strokeWidth="10"
          strokeLinecap="round"
        />
        {/* Zone tinting: red segment */}
        <path d={describeArc(START_DEG, SWEEP * 0.4)} fill="none" stroke="#FF3B5C" strokeWidth="10" strokeLinecap="round" opacity={0.15} />
        {/* Zone tinting: yellow segment */}
        <path d={describeArc(START_DEG + SWEEP * 0.4, SWEEP * 0.3)} fill="none" stroke="#FFB800" strokeWidth="10" strokeLinecap="round" opacity={0.15} />
        {/* Zone tinting: green segment */}
        <path d={describeArc(START_DEG + SWEEP * 0.7, SWEEP * 0.3)} fill="none" stroke="#00FF88" strokeWidth="10" strokeLinecap="round" opacity={0.15} />

        {/* Filled arc */}
        {filledSweep > 1 && (
          <path
            d={describeArc(START_DEG, filledSweep)}
            fill="none"
            stroke={scoreColor}
            strokeWidth="10"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 4px ${scoreColor}66)` }}
          />
        )}

        {/* Tick marks */}
        {[0, 25, 50, 75, 100].map((pct) => {
          const deg = START_DEG + (pct / 100) * SWEEP;
          const inner = { x: CX + (R - 16) * Math.cos(toRad(deg)), y: CY + (R - 16) * Math.sin(toRad(deg)) };
          const outer = { x: CX + (R - 6) * Math.cos(toRad(deg)), y: CY + (R - 6) * Math.sin(toRad(deg)) };
          return (
            <line key={pct}
              x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
              stroke="#334155" strokeWidth="1.5" strokeLinecap="round"
            />
          );
        })}

        {/* Needle */}
        {filledSweep > 0 && (
          <>
            <polygon
              points={`${needleTip.x},${needleTip.y} ${needleBase1.x},${needleBase1.y} ${needleBase2.x},${needleBase2.y}`}
              fill={scoreColor}
              opacity={0.9}
            />
            <circle cx={CX} cy={CY} r={5} fill={scoreColor} />
            <circle cx={CX} cy={CY} r={2.5} fill="#0a0f1a" />
          </>
        )}

        {/* Score label */}
        <text x={CX} y={CY + 22} textAnchor="middle" fill={scoreColor}
          fontSize="22" fontWeight="700" fontFamily="monospace">
          {score}
        </text>
        <text x={CX} y={CY + 35} textAnchor="middle" fill="#475569"
          fontSize="8" fontFamily="monospace" letterSpacing="1">
          / 100
        </text>

        {/* Zone labels */}
        <text x="18" y="118" fill="#FF3B5C" fontSize="7" fontFamily="monospace" opacity="0.7">RISK</text>
        <text x="145" y="118" fill="#00FF88" fontSize="7" fontFamily="monospace" opacity="0.7">SAFE</text>
      </svg>

      {/* Grade badge */}
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 flex flex-col items-center">
        <span className="text-xs font-bold px-2 py-0.5 rounded-md border"
          style={{ color: scoreColor, borderColor: `${scoreColor}40`, background: `${scoreColor}10` }}>
          {grade} · {gradeLabel}
        </span>
      </div>
    </div>
  );
}

// ── Sub-metric grid ────────────────────────────────────────────────────────────

function SubMetricGrid({ score }: { score: number }) {
  // Animate bar fills proportionally to score progress
  const pct = score / SCORE; // 0→1 as score counts up

  return (
    <div className="flex-1 grid grid-cols-2 gap-2 w-full">
      {SUB_METRICS.map((m) => {
        const barPct = Math.min((m.value / m.max) * pct * 100, 100);
        return (
          <div key={m.label} className="px-3 py-2" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--t-border)" }}>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] font-mono" style={{ color: "var(--t-muted)" }}>{m.label}</span>
              <span className="text-xs font-mono font-semibold" style={{ color: m.color }}>
                {(m.value * pct).toFixed(2)}{m.unit}
              </span>
            </div>
            <div className="w-full h-px overflow-hidden" style={{ background: "var(--t-border)" }}>
              <div
                className="h-px transition-all duration-100"
                style={{ width: `${barPct}%`, background: m.color, boxShadow: `0 0 4px ${m.color}66` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
