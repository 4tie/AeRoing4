'use client';
import { useEffect, useState } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { getStrategyDetail, StrategyDetail } from '@/lib/api';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { EquityChart } from '@/components/aero/EquityChart';

// ── Shared terminal primitives ────────────────────────────────────────────────
const Panel = ({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) => (
  <div className={`t-card ${className}`}>
    <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
      <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
      <span className="t-label">{label}</span>
    </div>
    <div className="p-3">{children}</div>
  </div>
);

export function TabRead() {
  const { selectedStrategyName } = useAeroStore();
  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getStrategyDetail(selectedStrategyName).then((d) => { setDetail(d); setLoading(false); });
  }, [selectedStrategyName]);

  if (loading) return (
    <div className="flex items-center gap-3 p-6" style={{ color: 'var(--t-muted)' }}>
      <span className="font-mono text-sm">loading strategy data</span>
      <span className="cursor-blink font-mono" style={{ color: 'var(--t-cyan)' }}>█</span>
    </div>
  );
  if (!detail) return null;

  return (
    <div className="space-y-4 max-w-7xl">
      {/* Page header */}
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 01 · READ</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>
          {detail.name}
        </h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>{detail.name}.py</span>
      </div>

      {/* Stat strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px" style={{ background: 'var(--t-border)', border: '1px solid var(--t-border)' }}>
        {[
          { label: 'TIMEFRAME',  value: detail.timeframe,                       color: 'var(--t-cyan)',  glow: 'rgba(0,229,255,0.08)'  },
          { label: 'STOPLOSS',   value: `${(detail.stoploss*100).toFixed(1)}%`, color: 'var(--t-red)',   glow: 'rgba(255,59,92,0.06)'  },
          { label: 'INDICATORS', value: String(detail.indicators.length),        color: 'var(--t-text)',  glow: 'transparent'           },
          { label: 'ROI STEPS',  value: String(detail.roi.length),               color: 'var(--t-text)',  glow: 'transparent'           },
        ].map(({ label, value, color, glow }) => (
          <div key={label} className="px-4 py-3" style={{ background: `linear-gradient(135deg, var(--t-card), ${glow})` }}>
            <span className="t-label block mb-1">{label}</span>
            <span className="text-xl font-bold font-mono" style={{ color, textShadow: color !== 'var(--t-text)' ? `0 0 12px ${color}` : 'none' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Middle row — key forces remount on strategy change so animations replay */}
      <div key={selectedStrategyName} className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Indicators */}
        <Panel label="INDICATORS">
          <div className="flex flex-wrap gap-2">
            {detail.indicators.map((ind, i) => (
              <span key={ind}
                className="indicator-tag px-2 py-1 text-xs font-mono"
                style={{
                  background: 'rgba(0,229,255,0.06)',
                  border: '1px solid var(--t-border-hi)',
                  color: 'var(--t-cyan)',
                  animationDelay: `${i * 60}ms`,
                }}>
                {ind}
              </span>
            ))}
          </div>
        </Panel>

        {/* ROI table */}
        <Panel label="MINIMAL ROI" className="lg:col-span-2">
          <div className="flex items-center justify-between mb-2 px-1">
            <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>After (min)</span>
            <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Target</span>
          </div>
          {detail.roi.map((r, i) => {
            const stagger = `${i * 80}ms`;
            const barDelay = `${i * 80 + 120}ms`;
            const valDelay = `${i * 80 + 200}ms`;
            const barPct = Math.min(100, r.roi * 100 * 6); // scale 0–10% ROI → 0–60% bar width
            return (
              <div key={i}
                className="roi-row flex items-center justify-between px-1 py-2"
                style={{
                  borderTop: i > 0 ? '1px solid var(--t-border)' : 'none',
                  animationDelay: stagger,
                }}>
                {/* Minutes label */}
                <span className="text-sm font-mono w-12 shrink-0" style={{ color: 'var(--t-label)' }}>
                  {r.minutes}m
                </span>

                {/* Animated fill bar */}
                <div className="flex-1 mx-3 h-px relative overflow-hidden" style={{ background: 'rgba(255,255,255,0.05)' }}>
                  <div
                    className="roi-bar absolute left-0 top-0 h-px"
                    style={{
                      width: `${barPct}%`,
                      background: 'linear-gradient(90deg, rgba(0,229,255,0.6), rgba(0,255,136,0.4))',
                      boxShadow: '0 0 4px rgba(0,229,255,0.5)',
                      animationDelay: barDelay,
                    }}
                  />
                </div>

                {/* Value badge */}
                <span
                  className="roi-value text-sm font-mono font-bold w-14 text-right shrink-0"
                  style={{
                    color: 'var(--t-green)',
                    textShadow: '0 0 8px rgba(0,255,136,0.45)',
                    animationDelay: valDelay,
                  }}>
                  {(r.roi * 100).toFixed(1)}%
                </span>
              </div>
            );
          })}
        </Panel>
      </div>

      {/* Equity curve */}
      <Panel label="EQUITY CURVE" className="t-card-glow">
        <EquityChart data={detail.equity} />
      </Panel>

      {/* Trades — key forces remount on strategy change so cascade replays */}
      <Panel key={`trades-${selectedStrategyName}`} label="RECENT TRADES">
        {/* Win/Loss summary */}
        <div className="flex items-center gap-3 mb-3 pb-3" style={{ borderBottom: '1px solid var(--t-border)' }}>
          {(() => {
            const wins   = detail.trades.filter(t => t.profit >= 0).length;
            const losses = detail.trades.length - wins;
            const pnl    = detail.trades.reduce((a, t) => a + t.profit, 0);
            return <>
              <div className="trade-summary-badge flex items-center gap-2 px-3 py-1.5"
                style={{ background: 'rgba(0,255,136,0.08)', border: '1px solid rgba(0,255,136,0.25)', animationDelay: '0ms' }}>
                <span className="t-label">WINS</span>
                <span className="text-xl font-bold font-mono" style={{ color: 'var(--t-green)', textShadow: '0 0 10px rgba(0,255,136,0.5)' }}>{wins}</span>
              </div>
              <div className="trade-summary-badge flex items-center gap-2 px-3 py-1.5"
                style={{ background: 'rgba(255,59,92,0.08)', border: '1px solid rgba(255,59,92,0.25)', animationDelay: '60ms' }}>
                <span className="t-label">LOSSES</span>
                <span className="text-xl font-bold font-mono" style={{ color: 'var(--t-red)', textShadow: '0 0 10px rgba(255,59,92,0.5)' }}>{losses}</span>
              </div>
              <div className="trade-summary-badge flex items-center gap-2 px-3 py-1.5 ml-2"
                style={{ background: pnl >= 0 ? 'rgba(0,255,136,0.06)' : 'rgba(255,59,92,0.06)', border: `1px solid ${pnl >= 0 ? 'rgba(0,255,136,0.2)' : 'rgba(255,59,92,0.2)'}`, animationDelay: '120ms' }}>
                <span className="t-label">NET PNL</span>
                <span className="text-xl font-bold font-mono" style={{ color: pnl >= 0 ? 'var(--t-green)' : 'var(--t-red)', textShadow: `0 0 10px ${pnl >= 0 ? 'rgba(0,255,136,0.5)' : 'rgba(255,59,92,0.5)'}` }}>
                  {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                </span>
              </div>
            </>;
          })()}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--t-border)' }}>
                {['PAIR','SIDE','PNL','%'].map(h => (
                  <th key={h} className="text-left pb-2 pr-6 last:text-right last:pr-0" style={{ color: 'var(--t-muted)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {detail.trades.slice(0, 14).map((trade, i) => {
                const win       = trade.profit >= 0;
                const rowDelay  = `${i * 40}ms`;
                const profDelay = `${i * 40 + 100}ms`;
                return (
                  <tr key={i}
                    className="trade-row"
                    style={{
                      borderBottom: '1px solid rgba(255,255,255,0.03)',
                      background: win ? 'rgba(0,255,136,0.03)' : 'rgba(255,59,92,0.03)',
                      borderLeft: `2px solid ${win ? 'rgba(0,255,136,0.35)' : 'rgba(255,59,92,0.35)'}`,
                      animationDelay: rowDelay,
                    }}>
                    <td className="py-2 pl-2 pr-5 font-semibold" style={{ color: 'var(--t-text)' }}>{trade.pair}</td>
                    <td className="py-2 pr-5">
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-mono font-bold"
                        style={{
                          background: trade.side === 'long' ? 'rgba(0,255,136,0.12)' : 'rgba(255,59,92,0.12)',
                          color: trade.side === 'long' ? 'var(--t-green)' : 'var(--t-red)',
                          border: `1px solid ${trade.side === 'long' ? 'rgba(0,255,136,0.3)' : 'rgba(255,59,92,0.3)'}`,
                        }}>
                        {trade.side === 'long' ? <ArrowUpRight size={9} /> : <ArrowDownRight size={9} />}
                        {trade.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 pr-5 text-[11px]" style={{ color: 'var(--t-muted)' }}>{trade.duration}</td>
                    <td className="py-2 text-right">
                      <span className="trade-profit font-bold text-sm inline-block" style={{
                        color: win ? 'var(--t-green)' : 'var(--t-red)',
                        textShadow: win ? '0 0 8px rgba(0,255,136,0.4)' : '0 0 8px rgba(255,59,92,0.4)',
                        animationDelay: profDelay,
                      }}>
                        {win ? '+' : ''}{trade.profit.toFixed(3)}%
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
