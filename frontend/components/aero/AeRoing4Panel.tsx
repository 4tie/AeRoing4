'use client';
import { useRef, useState } from 'react';
import { Play, Loader2, Clock, CheckCircle2, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';
import { useAeroStore } from '@/lib/aeroStore';
import {
  startAeRoing4Run, getAeRoing4Run,
  DEFAULT_DISCOVERY_UNIVERSE,
  type WorkflowStep,
  type PairDiscoveryResult,
} from '@/lib/api';
import { PairDiscoveryTable } from './PairDiscoveryTable';
import { ScoreDistributionChart } from './ScoreDistributionChart';

// ── Timerange presets ─────────────────────────────────────────────────────────

const TIMERANGE_PRESETS: { label: string; value: string }[] = [
  { label: '7d',   value: '20231225-20240101' },
  { label: '30d',  value: '20231202-20240101' },
  { label: '2m',   value: '20231101-20240101' },
  { label: '3m',   value: '20231001-20240101' },
  { label: '6m',   value: '20230701-20240101' },
  { label: '8m',   value: '20230501-20240101' },
  { label: '12m',  value: '20230101-20240101' },
  { label: '2y',   value: '20220101-20240101' },
  { label: '2y6m', value: '20210701-20240101' },
  { label: '3y',   value: '20210101-20240101' },
];

const DISCOVERY_UNIVERSE_OPTIONS = DEFAULT_DISCOVERY_UNIVERSE;

// ── ConfigPanel ───────────────────────────────────────────────────────────────

function ConfigPanel({ strategies, strategyName, setStrategyName, pairs, setPairs, timerange, setTimerange }: {
  strategies: string[]; strategyName: string; setStrategyName: (n: string) => void;
  pairs: string[]; setPairs: (p: string[]) => void;
  timerange: string; setTimerange: (t: string) => void;
}) {
  const [customPairsText, setCustomPairsText] = useState('');

  const activePairSet = pairs.length === 0 ? new Set(DISCOVERY_UNIVERSE_OPTIONS) : new Set(pairs);
  const allSelected   = pairs.length === 0 || pairs.length === DISCOVERY_UNIVERSE_OPTIONS.length;

  const togglePair = (p: string) => {
    const current = pairs.length === 0 ? [...DISCOVERY_UNIVERSE_OPTIONS] : [...pairs];
    setPairs(current.includes(p) ? current.filter(x => x !== p) : [...current, p]);
  };

  const selectAll   = () => setPairs([]);
  const unselectAll = () => setPairs([DISCOVERY_UNIVERSE_OPTIONS[0]]);

  const applyCustomPairs = () => {
    const parsed = customPairsText
      .split(/[\n,\s]+/)
      .map(s => s.trim().toUpperCase())
      .filter(s => s.includes('/'));
    if (parsed.length > 0) setPairs(parsed);
  };

  const countLabel = allSelected
    ? `${DISCOVERY_UNIVERSE_OPTIONS.length} pairs (all)`
    : `${pairs.length} selected`;

  return (
    <div className="t-card overflow-hidden">
      <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
        <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
        <span className="t-label">DISCOVERY CONFIG</span>
      </div>
      <div className="p-4 space-y-4">

        {/* Strategy */}
        <div>
          <span className="t-label block mb-1.5">STRATEGY</span>
          <select value={strategyName} onChange={e => setStrategyName(e.target.value)}
            className="w-full px-3 py-2 text-xs font-mono t-focus"
            style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}>
            {strategies.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        {/* Timerange presets + manual */}
        <div>
          <span className="t-label block mb-1.5">DISCOVERY TIMERANGE</span>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {TIMERANGE_PRESETS.map(p => {
              const active = timerange === p.value;
              return (
                <button key={p.value} onClick={() => setTimerange(p.value)}
                  className="px-2 py-1 text-[10px] font-mono transition-all"
                  style={{
                    border: `1px solid ${active ? 'var(--t-border-hi)' : 'var(--t-border)'}`,
                    background: active ? 'rgba(0,229,255,0.07)' : 'transparent',
                    color: active ? 'var(--t-cyan)' : 'var(--t-muted)',
                  }}>
                  {p.label}
                </button>
              );
            })}
          </div>
          <input type="text" value={timerange} onChange={e => setTimerange(e.target.value)}
            placeholder="YYYYMMDD-YYYYMMDD"
            className="w-full px-3 py-2 text-xs font-mono t-focus"
            style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} />
          <p className="text-[10px] font-mono mt-1" style={{ color: 'var(--t-muted)' }}>
            Smoke timerange (fixed): 20240101-20240108 · smoke pair: BTC/USDT
          </p>
        </div>

        {/* Universe */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="t-label flex-1">DISCOVERY UNIVERSE</span>
            <span className="text-[10px] font-mono" style={{ color: 'var(--t-muted)' }}>{countLabel}</span>
            <button onClick={selectAll}
              className="px-2 py-0.5 text-[9px] font-mono transition-all"
              style={{ border: '1px solid var(--t-border)', color: 'var(--t-cyan)', background: 'transparent' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,229,255,0.08)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
              ALL
            </button>
            <button onClick={unselectAll}
              className="px-2 py-0.5 text-[9px] font-mono transition-all"
              style={{ border: '1px solid var(--t-border)', color: 'var(--t-muted)', background: 'transparent' }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
              NONE
            </button>
          </div>

          <div className="flex flex-wrap gap-1.5 mb-3">
            {DISCOVERY_UNIVERSE_OPTIONS.map(p => {
              const sel = activePairSet.has(p);
              return (
                <button key={p} onClick={() => togglePair(p)}
                  className="px-2 py-1 text-[10px] font-mono transition-all"
                  style={{
                    border: `1px solid ${sel ? 'var(--t-border-hi)' : 'var(--t-border)'}`,
                    background: sel ? 'rgba(0,229,255,0.07)' : 'transparent',
                    color: sel ? 'var(--t-cyan)' : 'var(--t-muted)',
                  }}>
                  {p}
                </button>
              );
            })}
          </div>

          <div>
            <span className="t-label block mb-1">CUSTOM PAIRS (comma or newline separated)</span>
            <div className="flex gap-2">
              <textarea
                value={customPairsText}
                onChange={e => setCustomPairsText(e.target.value)}
                placeholder={'BTC/USDT, ETH/USDT\nSOL/BTC'}
                rows={2}
                className="flex-1 px-3 py-2 text-[11px] font-mono resize-none t-focus"
                style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
              />
              <button onClick={applyCustomPairs}
                className="px-3 text-[10px] font-mono font-bold self-stretch transition-all"
                style={{ border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)', background: 'rgba(0,229,255,0.06)', minWidth: 52 }}
                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,229,255,0.14)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'rgba(0,229,255,0.06)')}>
                APPLY
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Outcome banner ────────────────────────────────────────────────────────────

function OutcomeBanner({ outcome, result }: { outcome: string; result: PairDiscoveryResult | null }) {
  const isNoSignal = outcome === 'NO_SIGNAL_ACTIVITY';
  const isSuccess = outcome === 'SUCCESS';
  const color = isSuccess ? 'var(--t-green)' : isNoSignal ? 'var(--t-yellow)' : 'var(--t-red)';
  const background = isSuccess ? 'rgba(0,255,136,0.06)' : isNoSignal ? 'rgba(255,184,0,0.06)' : 'rgba(255,59,92,0.06)';
  const border = isSuccess ? 'rgba(0,255,136,0.25)' : isNoSignal ? 'rgba(255,184,0,0.25)' : 'rgba(255,59,92,0.25)';
  return (
    <div className="px-4 py-3 flex items-center gap-3"
      style={{ background, border: `1px solid ${border}` }}>
      <span className="text-lg" style={{ color }}>
        {isSuccess ? 'OK' : isNoSignal ? '!' : 'X'}
      </span>
      <div>
        <span className="text-sm font-mono font-bold" style={{ color }}>
          {isSuccess ? 'DISCOVERY COMPLETE' : isNoSignal ? 'no_signal_activity' : 'NO_PAIR_CANDIDATES'}
        </span>
        {isNoSignal && (
          <p className="text-[10px] font-mono mt-0.5" style={{ color: 'var(--t-muted)' }}>
            The backtest completed successfully, but this strategy produced no trades for the selected pair, timeframe, and timerange. Try a longer timerange, another pair, or the strategy&apos;s default timeframe.
          </p>
        )}
        {result && (
          <p className="text-[10px] font-mono mt-0.5" style={{ color: 'var(--t-muted)' }}>
            {result.valid_candidates} valid candidate{result.valid_candidates !== 1 ? 's' : ''} from {result.universe_size} pairs evaluated
          </p>
        )}
      </div>
    </div>
  );
}

function DiscoverySummaryStrip({ result }: { result: PairDiscoveryResult }) {
  const items = [
    { label: 'UNIVERSE',   value: String(result.universe_size),    color: 'var(--t-text)'  },
    { label: 'USABLE',     value: String(result.usable_pairs),     color: 'var(--t-text)'  },
    { label: 'EVALUATED',  value: String(result.evaluated_pairs),  color: 'var(--t-cyan)'  },
    { label: 'VALID',      value: String(result.valid_candidates), color: 'var(--t-green)' },
    { label: 'REJECTED',   value: String(result.rejected_pairs),   color: 'var(--t-red)'   },
  ];
  return (
    <div className="flex flex-wrap gap-px mb-1" style={{ background: 'var(--t-border)', border: '1px solid var(--t-border)' }}>
      {items.map(({ label, value, color }) => (
        <div key={label} className="px-4 py-2 flex-1" style={{ background: 'var(--t-card)', minWidth: 70 }}>
          <span className="t-label block">{label}</span>
          <span className="text-base font-bold font-mono" style={{ color }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

// ── StepCard ──────────────────────────────────────────────────────────────────

interface StepCardProps {
  step: WorkflowStep;
  enterDelay: number;
  isExpanded: boolean;
  onToggle: () => void;
  extra?: React.ReactNode;
}

function StepCard({ step, enterDelay, isExpanded, onToggle, extra }: StepCardProps) {
  const cfg: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
    pending:  { icon: <Clock size={12} />,                             color: 'var(--t-muted)',  label: 'PENDING'  },
    running:  { icon: <Loader2 size={12} className="animate-spin" />, color: 'var(--t-cyan)',   label: 'RUNNING'  },
    done:     { icon: <CheckCircle2 size={12} />,                      color: 'var(--t-green)',  label: 'DONE'     },
    error:    { icon: <AlertCircle size={12} />,                       color: 'var(--t-red)',    label: 'ERROR'    },
    skipped:  { icon: <span className="text-[10px]">⊘</span>,         color: 'var(--t-muted)',  label: 'SKIPPED'  },
  };
  const s = cfg[step.status] ?? cfg.pending;
  const borderColor =
    step.status === 'running' ? 'rgba(0,229,255,0.6)'  :
    step.status === 'error'   ? 'rgba(255,59,92,0.45)' :
    step.status === 'done'    ? 'rgba(0,255,136,0.25)' : 'var(--t-border)';
  const cardGlow =
    step.status === 'running' ? '0 0 20px rgba(0,229,255,0.07)' :
    step.status === 'done'    ? '0 0 12px rgba(0,255,136,0.05)' : 'none';

  return (
    <div className="stage-card-enter t-card overflow-hidden transition-all"
      style={{ borderColor, boxShadow: cardGlow, animationDelay: `${enterDelay}ms` }}>
      <button className="w-full flex items-center gap-3 px-3 py-2.5 text-left" onClick={onToggle}>
        <span className="stage-num-badge text-[10px] font-mono font-bold w-6 h-6 flex items-center justify-center shrink-0"
          style={{
            background: step.status === 'done' ? 'rgba(0,255,136,0.15)' : step.status === 'running' ? 'rgba(0,229,255,0.15)' : step.status === 'error' ? 'rgba(255,59,92,0.15)' : 'rgba(255,255,255,0.04)',
            color: s.color, border: `1px solid ${borderColor}`,
            textShadow: step.status !== 'pending' ? `0 0 8px ${s.color}` : 'none',
            animationDelay: `${enterDelay + 60}ms`,
          }}>
          {step.status === 'done' ? '✓' : step.status === 'error' ? '✕' : step.status === 'skipped' ? '⊘' : '·'}
        </span>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-semibold" style={{ color: 'var(--t-text)' }}>{step.name.toUpperCase()}</span>
            <span className="flex items-center gap-1 text-[10px] font-mono" style={{ color: s.color }}>{s.icon}{s.label}</span>
          </div>
          {step.status === 'running' && (
            <div className="mt-1.5 w-full h-px" style={{ background: 'var(--t-surface)' }}>
              <div className="h-px transition-all duration-500" style={{ width: `${step.progress}%`, background: 'var(--t-cyan)', boxShadow: '0 0 6px rgba(0,229,255,0.6)' }} />
            </div>
          )}
        </div>
        {isExpanded ? <ChevronDown size={12} style={{ color: 'var(--t-muted)' }} /> : <ChevronRight size={12} style={{ color: 'var(--t-muted)' }} />}
      </button>

      {isExpanded && (step.logs.length > 0 || extra) && (
        <div className="p-3 space-y-3" style={{ borderTop: '1px solid var(--t-border)', background: '#050505' }}>
          {extra}
          {step.logs.length > 0 && (
            <div className="text-xs font-mono space-y-0.5">
              {step.logs.map((log, i) => (
                <div key={i} className="stage-log-line"
                  style={{ color: log.includes('[OK]') ? 'var(--t-green)' : log.includes('[WARN]') ? 'var(--t-yellow)' : log.includes('[ERR]') ? 'var(--t-red)' : 'var(--t-muted)', animationDelay: `${i * 40}ms` }}>
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

// ── Main panel ────────────────────────────────────────────────────────────────

export function AeRoing4Panel() {
  const {
    aering4Run, setAering4Run,
    aering4Running, setAering4Running,
    discoveryPairs, setDiscoveryPairs,
    discoveryTimerange, setDiscoveryTimerange,
    aering4StrategyName, setAering4StrategyName,
    strategies,
  } = useAeroStore();

  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const strategyNames = strategies.map(s => s.name);

  // ── Start run against real backend ────────────────────────────────────────

  const handleStart = async () => {
    if (aering4Running) return;
    setError(null);
    setAering4Running(true);

    try {
      const initial = await startAeRoing4Run({
        strategy_name: aering4StrategyName,
        timeframe: '5m',
        smoke_timerange: '20240101-20240131',
        smoke_pairs: ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'],
        enable_pair_discovery: true,
        discovery_pairs: discoveryPairs.length > 0 ? discoveryPairs : undefined,
        discovery_timerange: discoveryTimerange || undefined,
      });

      setAering4Run(initial);
      const runId = initial._runId;

      // ── Poll for updates every 2 seconds ──────────────────────────────────
      const poll = async () => {
        try {
          const updated = await getAeRoing4Run(runId);
          setAering4Run(updated);

          if (updated.status === 'running' || updated.status === 'pending') {
            pollRef.current = setTimeout(poll, 2000);
          } else {
            setAering4Running(false);
          }
        } catch (e) {
          setAering4Running(false);
          setError(e instanceof Error ? e.message : 'Polling failed');
        }
      };

      pollRef.current = setTimeout(poll, 2000);
    } catch (e) {
      setAering4Running(false);
      setError(e instanceof Error ? e.message : 'Failed to start run');
    }
  };

  const handleReset = () => {
    if (pollRef.current) clearTimeout(pollRef.current);
    setAering4Run(null);
    setAering4Running(false);
    setError(null);
  };

  const run = aering4Run;
  const isTerminal = run && (run.status === 'done' || run.status === 'error');
  const discResult = run?.discovery_result ?? null;

  return (
    <div className="space-y-4">
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <span className="t-label block mb-0.5">AEROING4 · FAST PAIR DISCOVERY</span>
          <p className="text-[10px] font-mono" style={{ color: 'var(--t-muted)' }}>
            Validates strategy, runs smoke backtest, then ranks the discovery universe
          </p>
        </div>
        <div className="flex gap-2">
          {run && (
            <button onClick={handleReset} disabled={aering4Running}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-mono transition-all"
              style={{ border: '1px solid var(--t-border)', color: 'var(--t-muted)', background: 'transparent' }}
              onMouseEnter={e => !aering4Running && (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
              RESET
            </button>
          )}
          <button onClick={handleStart}
            disabled={aering4Running}
            className="flex items-center gap-2 px-4 py-1.5 text-xs font-mono font-bold transition-all"
            style={{
              border: `1px solid ${aering4Running ? 'var(--t-border)' : 'var(--t-cyan)'}`,
              background: aering4Running ? 'transparent' : 'rgba(0,229,255,0.08)',
              color: aering4Running ? 'var(--t-muted)' : 'var(--t-cyan)',
              cursor: aering4Running ? 'not-allowed' : 'pointer',
            }}>
            {aering4Running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {aering4Running ? 'RUNNING…' : 'RUN DISCOVERY'}
          </button>
        </div>
      </div>

      {/* ── Error banner ── */}
      {error && (
        <div className="px-4 py-2 text-xs font-mono" style={{ background: 'rgba(255,59,92,0.06)', border: '1px solid rgba(255,59,92,0.3)', color: 'var(--t-red)' }}>
          ✕ {error}
        </div>
      )}

      {/* ── Two-column layout when run is active ── */}
      <div className={`gap-4 ${run ? 'grid grid-cols-1 lg:grid-cols-2' : ''}`}>

        {/* Config panel */}
        <ConfigPanel
          strategies={strategyNames.length > 0 ? strategyNames : [aering4StrategyName]}
          strategyName={aering4StrategyName}
          setStrategyName={setAering4StrategyName}
          pairs={discoveryPairs}
          setPairs={setDiscoveryPairs}
          timerange={discoveryTimerange}
          setTimerange={setDiscoveryTimerange}
        />

        {/* Steps */}
        {run && (
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1 mb-1">
              <span className="t-label">WORKFLOW STEPS</span>
              <span className="text-[10px] font-mono" style={{ color: 'var(--t-muted)' }}>
                run: {run.id.slice(0, 8)}…
              </span>
            </div>
            {run.steps.map((step, idx) => (
              <StepCard
                key={step.id}
                step={step}
                enterDelay={idx * 55}
                isExpanded={expandedStep === step.id}
                onToggle={() => setExpandedStep(expandedStep === step.id ? null : step.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Outcome + discovery results ── */}
      {isTerminal && run?.outcome && run.outcome !== 'IN_PROGRESS' && (
        <div className="space-y-3">
          <OutcomeBanner outcome={run.outcome} result={discResult} />

          {discResult && (
            <>
              <DiscoverySummaryStrip result={discResult} />

              {discResult.ranked_pairs.filter(p => p.status === 'VALID_CANDIDATE').length > 0 && (
                <ScoreDistributionChart pairs={discResult.ranked_pairs} />
              )}

              <PairDiscoveryTable pairs={discResult.ranked_pairs} />
            </>
          )}
        </div>
      )}

      {/* ── Idle prompt ── */}
      {!run && !aering4Running && (
        <div className="flex items-center justify-center h-32 t-card" style={{ borderStyle: 'dashed' }}>
          <div className="text-center">
            <p className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>configure strategy and timerange, then press run</p>
          </div>
        </div>
      )}
    </div>
  );
}
