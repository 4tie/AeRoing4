'use client';
import { useEffect, useRef, useState } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { getStrategyDetail, getRiskMetrics, StrategyDetail, RiskMetrics } from '@/lib/api';
import { PieChart, Pie, Cell, Tooltip } from 'recharts';
import { AlertTriangle, RefreshCw, Zap } from 'lucide-react';

const Panel = ({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) => (
  <div className={`t-card ${className}`}>
    <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
      <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
      <span className="t-label">{label}</span>
    </div>
    <div className="p-3">{children}</div>
  </div>
);

export function TabLearn() {
  const { selectedStrategyName, aering4Run, setActiveTab } = useAeroStore();
  const [detail, setDetail]   = useState<StrategyDetail | null>(null);
  const [metrics, setMetrics] = useState<RiskMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Track the last run ID we refreshed metrics for to avoid duplicate fetches
  const lastRefreshedRun = useRef<string | null>(null);

  const fetchData = async (stratName: string, silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    const [d, m] = await Promise.all([
      getStrategyDetail(stratName),
      getRiskMetrics(stratName),
    ]);
    setDetail(d);
    setMetrics(m);
    setLoading(false);
    setRefreshing(false);
  };

  // Load when strategy changes
  useEffect(() => {
    fetchData(selectedStrategyName);
   
  }, [selectedStrategyName]);

  // Auto-refresh when an AeRoing4 run finishes — key on stable run.id (typed field)
  useEffect(() => {
    if (!aering4Run) return;
    const isDone = aering4Run.status === 'done';
    const runId  = aering4Run.id; // typed string field on AeRoing4RunState
    if (isDone && runId && runId !== lastRefreshedRun.current) {
      lastRefreshedRun.current = runId;
      fetchData(selectedStrategyName, true /* silent refresh */);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aering4Run?.status, aering4Run?.id]);

  /** Whether we have zero real metrics (no run data yet) */
  const hasNoRunData = metrics && metrics.winRate === 0 && metrics.sharpe === 0;

  if (loading || !detail || !metrics) return (
    <div className="flex items-center gap-3 p-6" style={{ color: 'var(--t-muted)' }}>
      <span className="font-mono text-sm">analyzing strategy</span>
      <span className="cursor-blink font-mono" style={{ color: 'var(--t-cyan)' }}>█</span>
    </div>
  );

  const winPie = [{ name: 'Win', value: metrics.winRate }, { name: 'Loss', value: 100 - metrics.winRate }];

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <span className="t-label block mb-1">TAB 01 · LEARN</span>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>{detail.name}</h1>
          <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Strategy breakdown &amp; risk analysis</span>
        </div>
        {refreshing && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-mono" style={{ border: '1px solid var(--t-border)', color: 'var(--t-cyan)' }}>
            <RefreshCw size={10} className="animate-spin" /> REFRESHING
          </div>
        )}
      </div>

      {/* No-run CTA — shown when metrics have no live backtest data */}
      {hasNoRunData && (
        <div className="p-4 flex items-start gap-3" style={{ background: 'rgba(255,184,0,0.04)', border: '1px solid rgba(255,184,0,0.25)' }}>
          <Zap size={14} style={{ color: 'var(--t-yellow)', flexShrink: 0, marginTop: 1 }} />
          <div className="flex-1">
            <span className="text-xs font-mono font-bold block mb-0.5" style={{ color: 'var(--t-yellow)' }}>NO DISCOVERY DATA</span>
            <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
              Win rate, Sharpe, and drawdown will populate automatically after an AeRoing4 run completes.
            </span>
          </div>
          <button
            onClick={() => setActiveTab('autoquant')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-mono shrink-0 transition-all"
            style={{ border: '1px solid rgba(255,184,0,0.4)', color: 'var(--t-yellow)', background: 'transparent' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,184,0,0.08)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <Zap size={10} /> RUN AEROING4
          </button>
        </div>
      )}

      {/* Risk metrics strip */}
      <div className="grid grid-cols-3 gap-px" style={{ background: 'var(--t-border)', border: '1px solid var(--t-border)' }}>
        {[
          { label: 'WIN RATE',     value: `${metrics.winRate.toFixed(1)}%`,     color: 'var(--t-green)', glow: 'rgba(0,255,136,0.07)'  },
          { label: 'SHARPE RATIO', value: metrics.sharpe.toFixed(2),             color: 'var(--t-cyan)',  glow: 'rgba(0,229,255,0.07)'  },
          { label: 'MAX DRAWDOWN', value: `-${metrics.maxDrawdown.toFixed(1)}%`, color: 'var(--t-red)',   glow: 'rgba(255,59,92,0.07)'  },
        ].map(({ label, value, color, glow }) => (
          <div key={label} className="px-4 py-3" style={{ background: `linear-gradient(135deg, var(--t-card), ${glow})` }}>
            <span className="t-label block mb-1">{label}</span>
            <span className="text-2xl font-bold font-mono" style={{ color, textShadow: `0 0 14px ${color}` }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Win/loss pie + logic */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel label="WIN / LOSS DISTRIBUTION">
          <div className="flex items-center gap-4">
            <div style={{ width: 120, height: 120 }}>
              <PieChart width={120} height={120}>
                <Pie dataKey="value" data={winPie} cx={60} cy={60} innerRadius={32} outerRadius={50} paddingAngle={2}>
                  <Cell fill="#00FF88" />
                  <Cell fill="#FF3B5C" />
                </Pie>
                <Tooltip contentStyle={{ background: '#0d0d0d', border: '1px solid rgba(0,229,255,0.2)', borderRadius: 0, fontSize: 11, fontFamily: 'monospace' }} />
              </PieChart>
            </div>
            <div className="space-y-2 text-sm font-mono">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 inline-block" style={{ background: 'var(--t-green)' }} />
                <span style={{ color: 'var(--t-muted)' }}>WIN <span style={{ color: 'var(--t-green)' }} className="font-bold">{metrics.winRate.toFixed(1)}%</span></span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 inline-block" style={{ background: 'var(--t-red)' }} />
                <span style={{ color: 'var(--t-muted)' }}>LOSS <span style={{ color: 'var(--t-red)' }} className="font-bold">{(100 - metrics.winRate).toFixed(1)}%</span></span>
              </div>
            </div>
          </div>
        </Panel>

        <Panel label="STRATEGY PARAMS">
          <div className="space-y-3">
            <div className="p-2" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--t-border)' }}>
              <span className="text-[10px] font-mono font-bold mb-1.5 block" style={{ color: 'var(--t-cyan)' }}>CONFIG</span>
              {[
                { k: 'TIMEFRAME',  v: detail.timeframe },
                { k: 'STOPLOSS',   v: `${(detail.stoploss * 100).toFixed(1)}%` },
                { k: 'ROI STEPS',  v: detail.roi.length > 0 ? detail.roi.map(r => `${r.minutes}m→${(r.roi*100).toFixed(1)}%`).join(' · ') : '—' },
              ].map(({ k, v }) => (
                <div key={k} className="text-xs font-mono flex items-start gap-2 mb-1" style={{ color: 'var(--t-muted)' }}>
                  <span className="shrink-0" style={{ color: 'var(--t-cyan)' }}>›</span>
                  <span className="shrink-0 font-bold" style={{ color: 'var(--t-label)' }}>{k}</span>
                  <span className="ml-auto font-bold" style={{ color: 'var(--t-text)' }}>{v}</span>
                </div>
              ))}
            </div>
            <div className="p-2" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--t-border)' }}>
              <span className="text-[10px] font-mono font-bold mb-1.5 block" style={{ color: 'var(--t-yellow)' }}>RUN AEROING4 TO ANALYSE</span>
              <div className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
                Switch to the <span style={{ color: 'var(--t-cyan)' }}>AutoQuant</span> tab to run the full
                discovery pipeline — pair filtering, smoke backtesting, and pair ranking.
                Results will populate the risk metrics above.
              </div>
            </div>
          </div>
        </Panel>
      </div>

      {/* Indicators */}
      <Panel label="INDICATORS">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {detail.indicators.map((ind) => (
            <div key={ind} className="p-2" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
              <span className="text-xs font-mono font-bold" style={{ color: 'var(--t-cyan)' }}>{ind}</span>
              <p className="text-[11px] font-mono mt-0.5" style={{ color: 'var(--t-muted)' }}>Trend/momentum signal · entry conditions</p>
            </div>
          ))}
        </div>
      </Panel>

      {/* Why it loses */}
      <Panel label="⚠ RISK FLAGS">
        <div className="space-y-2">
          {metrics.lossBullets.map((b, i) => (
            <div key={i} className="flex items-start gap-2 text-xs font-mono py-1.5" style={{ borderBottom: '1px solid var(--t-border)', color: 'var(--t-red)' }}>
              <AlertTriangle size={11} className="shrink-0 mt-0.5" />
              <span style={{ color: 'var(--t-text)' }}>{b}</span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
