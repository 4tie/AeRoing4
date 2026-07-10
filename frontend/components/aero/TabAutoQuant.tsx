"use client";
import { useState, useEffect, useRef } from "react";
import { useAeroStore } from "@/lib/aeroStore";
import { startPipelineRun } from "@/lib/api";
import type { StageStatus } from "@/lib/api";
import { Play, CheckCircle2, AlertCircle, Clock, Loader2, ChevronDown, ChevronRight } from "lucide-react";
import { StressTestHeatmap } from "@/components/aero/StressTestHeatmap";
import { RiskScoreGauge } from "@/components/aero/RiskScoreGauge";
import { AeRoing4Panel } from "@/components/aero/AeRoing4Panel";

type AQMode = "legacy" | "aering4";

const ALL_PAIRS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","AVAX/USDT","MATIC/USDT","ADA/USDT"];

const STAGE_LOGS: Record<number, string[]> = {
  1: ["[INFO] Fetching OHLCV data from exchange...", "[INFO] Loaded 4096 candles for BTC/USDT", "[INFO] Loaded 4096 candles for ETH/USDT", "[OK] Data validation passed"],
  2: ["[INFO] Computing baseline metrics...", "[INFO] BTC/USDT → Profit: +12.4%, DD: -8.2%", "[INFO] ETH/USDT → Profit: +9.1%, DD: -11.3%", "[OK] Baseline complete"],
  3: ["[INFO] Starting WFA hyperopt (100 epochs)...", "[INFO] Epoch 1/100: loss=0.847", "[INFO] Epoch 25/100: loss=0.623", "[INFO] Epoch 50/100: loss=0.441", "[INFO] Epoch 75/100: loss=0.312", "[OK] Hyperopt finished — best params found"],
  4: ["[INFO] Running overfit detection...", "[INFO] Checking stoploss parameter... PASS", "[INFO] Checking roi.0 parameter... PASS", "[INFO] Checking ema_period parameter... PASS", "[WARN] roi.30 shows overfit signal — review recommended", "[OK] Detection complete"],
  5: ["[INFO] Stress testing on 5 market scenarios...", "[INFO] Bear market 2022: -18% (within threshold)", "[INFO] Flash crash June 2023: -6.2%", "[INFO] Bull run 2021: +44.7%", "[OK] All stress tests passed"],
  6: ["[INFO] Computing final risk score...", "[INFO] Sharpe: 1.24 | Sortino: 1.87 | Calmar: 0.91", "[INFO] Portfolio correlation: LOW", "[OK] Risk assessment complete — Score: 82/100"],
};

export function TabAutoQuant() {
  const [mode, setMode] = useState<AQMode>("aering4");
  const { pipelineRun, setPipelineRun, updateStage, appendLog, pipelineRunning, setPipelineRunning, selectedPairs, setSelectedPairs } = useAeroStore();
  const [expandedStage, setExpandedStage] = useState<number | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const allLogs = pipelineRun?.stages.flatMap(s => s.logs.map(l => `[S${s.id}] ${l}`)) ?? [];

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [allLogs.length]);

  const simulateStage = (stageId: number) => {
    const logs = STAGE_LOGS[stageId] ?? [];
    let li = 0, prog = 0;
    updateStage(stageId, { status: "running", progress: 0 });
    const tick = () => {
      prog = Math.min(100, prog + Math.random() * 18 + 5);
      if (li < logs.length) appendLog(stageId, logs[li++]);
      if (prog < 100) { simRef.current = setTimeout(tick, 350 + Math.random() * 300); }
      else {
        updateStage(stageId, { status: "done", progress: 100 });
        if (stageId < 6) setTimeout(() => simulateStage(stageId + 1), 500);
        else { setPipelineRunning(false); setPipelineRun({ ...pipelineRun!, status: "done", currentStage: 6 }); }
      }
    };
    simRef.current = setTimeout(tick, 400);
  };

  const handleStart = async () => {
    if (simRef.current) clearTimeout(simRef.current);
    setPipelineRunning(true);
    const run = await startPipelineRun(selectedPairs);
    setPipelineRun(run);
    simulateStage(1);
  };

  const togglePair = (p: string) => setSelectedPairs(selectedPairs.includes(p) ? selectedPairs.filter(x => x !== p) : [...selectedPairs, p]);

  return (
    <div className="space-y-4 max-w-5xl">
      {/* ── Header + mode switcher ── */}
      <div className="flex items-start justify-between flex-wrap gap-3 mb-1">
        <div>
          <span className="t-label block mb-1">TAB 05 · AUTOQUANT</span>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: "var(--t-text)", letterSpacing: "-0.02em" }}>
            AutoQuant
          </h1>
        </div>
        {/* Mode switcher */}
        <div className="flex items-stretch" style={{ border: "1px solid var(--t-border)" }}>
          {(["aering4", "legacy"] as AQMode[]).map(m => (
            <button key={m} onClick={() => setMode(m)}
              className="px-4 py-1.5 text-xs font-mono font-bold transition-all"
              style={{ background: mode === m ? "rgba(0,229,255,0.1)" : "transparent", color: mode === m ? "var(--t-cyan)" : "var(--t-muted)", borderRight: m === "aering4" ? "1px solid var(--t-border)" : "none" }}>
              {m === "aering4" ? "AERING4 ✦" : "LEGACY PIPELINE"}
            </button>
          ))}
        </div>
      </div>

      {/* ── AeRoing4 mode ── */}
      {mode === "aering4" && <>
        <ResearchPipeline />
        <AeRoing4Panel />
      </>}

      {/* ── Legacy pipeline mode ── */}
      {mode === "legacy" && <>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <span className="text-xs font-mono" style={{ color: "var(--t-muted)" }}>Legacy 6-stage AutoQuant pipeline</span>
          <button onClick={handleStart} disabled={pipelineRunning}
          className="flex items-center gap-2 px-4 py-2 text-sm font-mono font-bold transition-all disabled:opacity-40"
          style={{ background: "rgba(0,229,255,0.08)", border: "1px solid var(--t-border-hi)", color: "var(--t-cyan)" }}
          onMouseEnter={e => !pipelineRunning && (e.currentTarget.style.background = "rgba(0,229,255,0.15)")}
          onMouseLeave={e => !pipelineRunning && (e.currentTarget.style.background = "rgba(0,229,255,0.08)")}>
          {pipelineRunning ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {pipelineRunning ? "RUNNING..." : "START PIPELINE"}
        </button>
      </div>

      {/* Pair selection */}
      {!pipelineRun && (
        <div className="t-card">
          <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: "1px solid var(--t-border)" }}>
            <span className="w-1.5 h-1.5 shrink-0" style={{ background: "var(--t-cyan)" }} />
            <span className="t-label">SELECT PAIRS</span>
          </div>
          <div className="p-3 flex flex-wrap gap-2">
            {ALL_PAIRS.map(p => (
              <button key={p} onClick={() => togglePair(p)}
                className="px-3 py-1.5 text-xs font-mono transition-all"
                style={{ border: `1px solid ${selectedPairs.includes(p) ? "var(--t-border-hi)" : "var(--t-border)"}`, background: selectedPairs.includes(p) ? "rgba(0,229,255,0.08)" : "transparent", color: selectedPairs.includes(p) ? "var(--t-cyan)" : "var(--t-label)" }}>
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Stepper */}
      {pipelineRun && (
        <div className="space-y-2">
          {pipelineRun.stages.map((stage, idx) => (
            <StageCard key={stage.id} stage={stage}
              enterDelay={idx * 55}
              isExpanded={expandedStage === stage.id}
              onToggle={() => setExpandedStage(expandedStage === stage.id ? null : stage.id)}
              isLast={idx === pipelineRun.stages.length - 1}
              extra={
                stage.id === 5 && (stage.status === "running" || stage.status === "done")
                  ? <StressTestHeatmap active={expandedStage === 5 && (stage.status === "running" || stage.status === "done")} />
                  : stage.id === 6 && (stage.status === "running" || stage.status === "done")
                    ? <RiskScoreGauge active={expandedStage === 6 && (stage.status === "running" || stage.status === "done")} />
                    : undefined
              }
            />
          ))}
        </div>
      )}

      {!pipelineRun && (
        <div className="flex items-center justify-center h-40 t-card" style={{ borderStyle: "dashed" }}>
          <p className="text-xs font-mono" style={{ color: "var(--t-muted)" }}>select pairs and start pipeline to begin</p>
        </div>
      )}

      {/* Console */}
      {pipelineRun && (
        <div className="t-card overflow-hidden">
          <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: "1px solid var(--t-border)", background: "rgba(0,0,0,0.3)" }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: pipelineRunning ? "var(--t-green)" : "var(--t-muted)", boxShadow: pipelineRunning ? "0 0 6px var(--t-green)" : "none" }} />
            <span className="t-label">PIPELINE CONSOLE</span>
          </div>
          <div ref={logRef} className="h-44 overflow-y-auto p-3 text-xs font-mono space-y-0.5" style={{ background: "#050505" }}>
            {allLogs.length === 0
              ? <span style={{ color: "var(--t-muted)" }}>$ waiting for pipeline...</span>
              : allLogs.map((line, i) => (
                <div key={i} className="leading-relaxed" style={{ color: line.includes("[OK]") ? "var(--t-green)" : line.includes("[WARN]") ? "var(--t-yellow)" : line.includes("[ERR]") ? "var(--t-red)" : "var(--t-muted)" }}>
                  <span style={{ color: "rgba(255,255,255,0.1)" }} className="mr-2">{String(i + 1).padStart(3, "0")}</span>{line}
                </div>
              ))
            }
          </div>
        </div>
      )}
      </>}
    </div>
  );
}

// ── Research Pipeline Roadmap (Ollama/Backend/Freq workflow) ──────────────────

const PIPELINE_STAGES = [
  { id: 1,  name: "Strategy Validation",     group: "Pre-research",      agent: "backend" },
  { id: 2,  name: "Data Preparation",        group: "Pre-research",      agent: "backend" },
  { id: 3,  name: "Smoke Test",              group: "Pre-research",      agent: "freqtrade" },
  { id: 4,  name: "Initial Bias Check",      group: "Bias / Discovery",  agent: "freqtrade" },
  { id: 5,  name: "Pair Discovery",          group: "Bias / Discovery",  agent: "freqtrade" },
  { id: 6,  name: "Pair Selection",          group: "Bias / Discovery",  agent: "user" },
  { id: 7,  name: "Portfolio Baseline",      group: "Baseline",          agent: "freqtrade" },
  { id: 8,  name: "Deterministic Diagnosis", group: "Baseline",          agent: "backend" },
  { id: 9,  name: "Ollama Research Loop",    group: "AI Loop",           agent: "ollama" },
  { id: 10, name: "Focused Hyperopt",        group: "AI Loop",           agent: "freqtrade" },
  { id: 11, name: "Parameter Sensitivity",   group: "AI Loop",           agent: "freqtrade" },
  { id: 12, name: "Pre-Unseen Confirmation", group: "Validation",        agent: "freqtrade" },
  { id: 13, name: "Final Validation",        group: "Validation",        agent: "backend" },
  { id: 14, name: "Final Unseen Backtest",   group: "Validation",        agent: "freqtrade" },
  { id: 15, name: "Delivery",                group: "Validation",        agent: "backend" },
];

const AGENT_COLORS: Record<string, string> = {
  backend:   "#00E5FF",
  freqtrade: "#00FF88",
  ollama:    "#FFB800",
  user:      "#888888",
};

function ResearchPipeline() {
  const groups = Array.from(new Set(PIPELINE_STAGES.map(s => s.group)));
  return (
    <div className="t-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <span className="t-label block mb-1">RESEARCH PIPELINE</span>
          <span className="text-xs font-mono" style={{ color: "var(--t-muted)" }}>15-stage workflow: AI diagnoses → Backend constrains → Freqtrade tests</span>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono" style={{ color: "var(--t-muted)" }}>
          {Object.entries(AGENT_COLORS).map(([agent, color]) => (
            <span key={agent} className="flex items-center gap-1">
              <span className="w-1.5 h-1.5" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
              {agent.toUpperCase()}
            </span>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {groups.map(group => (
          <div key={group} className="p-3" style={{ background: "var(--t-bg)", border: "1px solid var(--t-border)" }}>
            <span className="t-label block mb-2">{group.toUpperCase()}</span>
            <div className="space-y-2">
              {PIPELINE_STAGES.filter(s => s.group === group).map(s => (
                <div key={s.id} className="flex items-center gap-2">
                  <span className="text-[10px] font-mono w-4" style={{ color: "var(--t-muted)" }}>{String(s.id).padStart(2, "0")}</span>
                  <span className="w-1.5 h-1.5 shrink-0" style={{ background: AGENT_COLORS[s.agent], boxShadow: `0 0 6px ${AGENT_COLORS[s.agent]}` }} />
                  <span className="text-[11px] font-mono" style={{ color: "var(--t-label)" }}>{s.name}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="p-2 text-[10px] font-mono" style={{ color: "var(--t-muted)", background: "rgba(0,229,255,0.03)", border: "1px solid var(--t-border)" }}>
        // AI proposes · Backend validates · Freqtrade tests · System decides
      </div>
    </div>
  );
}

function StageCard({ stage, isExpanded, onToggle, isLast, extra, enterDelay = 0 }: { stage: StageStatus; isExpanded: boolean; onToggle: () => void; isLast: boolean; extra?: React.ReactNode; enterDelay?: number }) {
  void isLast;
  const cfg: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
    pending: { icon: <Clock size={12} />,                             color: "var(--t-muted)",  label: "PENDING" },
    running: { icon: <Loader2 size={12} className="animate-spin" />, color: "var(--t-cyan)",   label: "RUNNING" },
    done:    { icon: <CheckCircle2 size={12} />,                      color: "var(--t-green)",  label: "DONE"    },
    error:   { icon: <AlertCircle size={12} />,                       color: "var(--t-red)",    label: "ERROR"   },
  };
  const s = cfg[stage.status];
  const borderColor = stage.status === "running" ? "rgba(0,229,255,0.6)" : stage.status === "error" ? "rgba(255,59,92,0.45)" : stage.status === "done" ? "rgba(0,255,136,0.25)" : "var(--t-border)";
  const cardGlow = stage.status === "running" ? "0 0 20px rgba(0,229,255,0.07), inset 0 0 30px rgba(0,229,255,0.03)" : stage.status === "done" ? "0 0 12px rgba(0,255,136,0.05)" : "none";

  return (
    <div className="stage-card-enter t-card overflow-hidden transition-all"
      style={{ borderColor, boxShadow: cardGlow, animationDelay: `${enterDelay}ms` }}>
      <button className="w-full flex items-center gap-3 px-3 py-2.5 text-left" onClick={onToggle}>
        <span className="stage-num-badge text-xs font-mono font-bold w-6 h-6 flex items-center justify-center shrink-0"
          style={{
            background: stage.status === "done" ? "rgba(0,255,136,0.15)" : stage.status === "running" ? "rgba(0,229,255,0.15)" : stage.status === "error" ? "rgba(255,59,92,0.15)" : "rgba(255,255,255,0.04)",
            color: s.color,
            border: `1px solid ${borderColor}`,
            textShadow: stage.status !== "pending" ? `0 0 8px ${s.color}` : "none",
            animationDelay: `${enterDelay + 60}ms`,
          }}>
          {stage.id}
        </span>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-semibold" style={{ color: "var(--t-text)" }}>{stage.name.toUpperCase()}</span>
            <span className="flex items-center gap-1 text-[10px] font-mono" style={{ color: s.color }}>{s.icon}{s.label}</span>
          </div>
          {stage.status === "running" && (
            <div className="mt-1.5 w-full h-px" style={{ background: "var(--t-surface)" }}>
              <div className="h-px transition-all duration-500" style={{ width: `${stage.progress}%`, background: "var(--t-cyan)", boxShadow: "0 0 6px rgba(0,229,255,0.6)" }} />
            </div>
          )}
        </div>
        {isExpanded ? <ChevronDown size={12} style={{ color: "var(--t-muted)" }} /> : <ChevronRight size={12} style={{ color: "var(--t-muted)" }} />}
      </button>

      {isExpanded && (stage.logs.length > 0 || extra) && (
        <div className="p-3 space-y-3" style={{ borderTop: "1px solid var(--t-border)", background: "#050505" }}>
          {extra}
          {stage.logs.length > 0 && (
            <div className="text-xs font-mono space-y-0.5">
              {stage.logs.map((log, i) => (
                <div key={i}
                  className="stage-log-line"
                  style={{
                    color: log.includes("[OK]") ? "var(--t-green)" : log.includes("[WARN]") ? "var(--t-yellow)" : "var(--t-muted)",
                    animationDelay: `${i * 45}ms`,
                  }}>
                  {log}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
