'use client';
import { useState, useEffect } from 'react';
import { runBacktest, BacktestResult, getStrategies } from '@/lib/api';
import { Play, Download } from 'lucide-react';

const ALL_PAIRS = [
  'BTC/USDT','ETH/USDT','BNB/USDT','SOL/USDT','ADA/USDT','AVAX/USDT','DOT/USDT','MATIC/USDT',
  'LINK/USDT','UNI/USDT','ATOM/USDT','LTC/USDT','XRP/USDT','DOGE/USDT','NEAR/USDT','APE/USDT',
  'FTM/USDT','ALGO/USDT','ICP/USDT','ETC/USDT','SAND/USDT','MANA/USDT','CRV/USDT','AAVE/USDT',
  'SUSHI/USDT','FIL/USDT','TRX/USDT','XLM/USDT','BCH/USDT','EOS/USDT','XTZ/USDT','VET/USDT',
  'THETA/USDT','IOTA/USDT','HBAR/USDT','XMR/USDT','DASH/USDT','ZEC/USDT','KAVA/USDT','RUNE/USDT',
  'AXS/USDT','SAND/USDT','MANA/USDT','GALA/USDT','ENJ/US','CHZ/USDT','SNX/USDT','MKR/USDT',
  'COMP/USDT','YFI/USDT','UMA/USDT','BAND/USDT','REN/USDT','KNC/USDT','BAL/USDT','CRV/USDT'
];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

const TIMERANGE_PRESETS = [
  { label: '7 days', value: '20240101-20240108' },
  { label: '30 days', value: '20231202-20240101' },
  { label: '3 months', value: '20231001-20240101' },
  { label: '6 months', value: '20230701-20240101' },
  { label: '1 year', value: '20230101-20240101' },
  { label: '2 years', value: '20220101-20240101' },
  { label: 'Custom', value: '' },
];

const Panel = ({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) => (
  <div className={`t-card ${className}`}>
    <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
      <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
      <span className="t-label">{label}</span>
    </div>
    <div className="p-3">{children}</div>
  </div>
);

export function TabTest() {
  const [strategies, setStrategies] = useState<string[]>([]);
  const [strategy, setStrategy] = useState('');
  const [timeframe, setTimeframe] = useState('5m');
  const [timerangePreset, setTimerangePreset] = useState('20230101-20240101');
  const [timerangeCustom, setTimerangeCustom] = useState('');
  const [maxOpenTrades, setMaxOpenTrades] = useState(5);
  const [pairs, setPairs] = useState(['BTC/USDT','ETH/USDT']);
  const [stakeAmount, setStakeAmount] = useState(100);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<BacktestResult | null>(null);

  const timerange = timerangePreset || timerangeCustom;

  useEffect(() => {
    getStrategies().then(strats => setStrategies(strats.map(s => s.name))).catch(() => setStrategies([]));
  }, []);

  const togglePair = (p: string) => setPairs(prev => prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]);

  const start = async () => {
    if (!strategy) return;
    setRunning(true); setResult(null); setProgress(0);
    const iv = setInterval(() => setProgress(p => { if (p >= 95) { clearInterval(iv); return 95; } return p + Math.random() * 12; }), 200);
    const r = await runBacktest({ strategy, timeframe, pairs, timerange, stakeAmount, maxOpenTrades });
    clearInterval(iv); setProgress(100);
    setTimeout(() => { setResult(r); setRunning(false); }, 300);
  };

  const download = () => {
    if (!result) return;
    const b = new Blob([JSON.stringify({ config: { pairs, timerange, stakeAmount }, result }, null, 2)], { type: 'application/json' });
    const u = URL.createObjectURL(b); const a = document.createElement('a');
    a.href = u; a.download = `aero-bt-${Date.now()}.json`; a.click(); URL.revokeObjectURL(u);
  };

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 04 · TEST</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>Backtest</h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Configure and run backtests against historical data</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Config */}
        <div className="space-y-4">
          <Panel label="CONFIGURATION">
            <div className="space-y-3">
              <div>
                <span className="t-label block mb-1">STRATEGY</span>
                <select value={strategy} onChange={e => setStrategy(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono t-focus"
                  style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}>
                  <option value="">Select strategy...</option>
                  {strategies.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div>
                <span className="t-label block mb-1">TIMEFRAME</span>
                <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono t-focus"
                  style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}>
                  {TIMEFRAMES.map(tf => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </div>
              {[
                { label: 'MAX OPEN TRADES', value: String(maxOpenTrades), set: (v: string) => setMaxOpenTrades(Number(v)), type: 'number' },
                { label: 'STAKE AMOUNT (USDT)', value: String(stakeAmount), set: (v: string) => setStakeAmount(Number(v)), type: 'number' },
              ].map(({ label, value, set, type }) => (
                <div key={label}>
                  <span className="t-label block mb-1">{label}</span>
                  <input type={type} value={value} onChange={e => set(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono t-focus"
                    style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} />
                </div>
              ))}
              <div>
                <span className="t-label block mb-1">TIMERANGE</span>
                <select value={timerangePreset} onChange={e => setTimerangePreset(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono t-focus mb-2"
                  style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}>
                  {TIMERANGE_PRESETS.map(preset => (
                    <option key={preset.value} value={preset.value}>{preset.label}</option>
                  ))}
                </select>
                {!timerangePreset && (
                  <input type="text" value={timerangeCustom} onChange={e => setTimerangeCustom(e.target.value)}
                    placeholder="YYYYMMDD-YYYYMMDD"
                    className="w-full px-3 py-2 text-xs font-mono t-focus"
                    style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} />
                )}
              </div>
            </div>
          </Panel>

          <Panel label="PAIRS">
            {ALL_PAIRS.map(p => (
              <label key={p} className="flex items-center gap-2 py-1 cursor-pointer group">
                <div onClick={() => togglePair(p)}
                  className="w-3.5 h-3.5 flex items-center justify-center cursor-pointer transition-all"
                  style={{ border: `1px solid ${pairs.includes(p) ? 'var(--t-cyan)' : 'var(--t-border)'}`, background: pairs.includes(p) ? 'rgba(0,229,255,0.1)' : 'transparent' }}>
                  {pairs.includes(p) && <span className="text-[8px] font-bold" style={{ color: 'var(--t-cyan)' }}>✓</span>}
                </div>
                <span className="text-xs font-mono" style={{ color: pairs.includes(p) ? 'var(--t-cyan)' : 'var(--t-label)' }}>{p}</span>
              </label>
            ))}
          </Panel>

          <button onClick={start} disabled={running || pairs.length === 0 || !strategy}
            className="w-full flex items-center justify-center gap-2 py-2.5 text-sm font-mono font-bold transition-all disabled:opacity-40"
            style={{ background: 'rgba(0,229,255,0.08)', border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)' }}
            onMouseEnter={e => !running && (e.currentTarget.style.background = 'rgba(0,229,255,0.15)')}
            onMouseLeave={e => !running && (e.currentTarget.style.background = 'rgba(0,229,255,0.08)')}>
            {running ? <span className="cursor-blink" style={{ color: 'var(--t-cyan)' }}>█</span> : <Play size={13} />}
            {running ? 'RUNNING...' : 'RUN BACKTEST'}
          </button>
        </div>

        {/* Results */}
        <div className="lg:col-span-2 space-y-4">
          {running && (
            <Panel label="RUNNING BACKTEST">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>{pairs.join(', ')} · {timerange}</span>
                <span className="text-sm font-mono font-bold" style={{ color: 'var(--t-cyan)' }}>{Math.min(100, Math.round(progress))}%</span>
              </div>
              <div className="w-full h-1" style={{ background: 'var(--t-surface)' }}>
                <div className="h-1 transition-all duration-300"
                  style={{ width: `${Math.min(100, progress)}%`, background: 'var(--t-cyan)', boxShadow: '0 0 8px rgba(0,229,255,0.5)' }} />
              </div>
              <div className="mt-3 space-y-1">
                {['Fetching candles...', 'Applying strategy logic...', 'Calculating metrics...'].map((l, i) => (
                  <div key={i} className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>› {l}</div>
                ))}
              </div>
            </Panel>
          )}

          {result && (
            <>
              <div className="grid grid-cols-2 gap-px" style={{ background: 'var(--t-border)', border: '1px solid var(--t-border)' }}>
                {[
                  { label: 'TOTAL TRADES',  value: String(result.totalTrades),                       color: 'var(--t-text)'  },
                  { label: 'WIN RATE',      value: `${result.winRate.toFixed(1)}%`,                  color: 'var(--t-green)' },
                  { label: 'PROFIT',        value: `${result.profitPct >= 0 ? '+' : ''}${result.profitPct.toFixed(2)}%`, color: result.profitPct >= 0 ? 'var(--t-green)' : 'var(--t-red)' },
                  { label: 'MAX DRAWDOWN',  value: `-${result.drawdown.toFixed(1)}%`,                color: 'var(--t-red)'   },
                ].map(({ label, value, color }) => (
                  <div key={label} className="px-4 py-3" style={{ background: 'var(--t-card)' }}>
                    <span className="t-label block mb-1">{label}</span>
                    <span className="text-xl font-bold font-mono" style={{ color }}>{value}</span>
                  </div>
                ))}
              </div>
              <Panel label="FINAL EQUITY">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="t-label block mb-1">FINAL BALANCE</span>
                    <span className="text-3xl font-bold font-mono" style={{ color: result.finalEquity >= 1000 ? 'var(--t-green)' : 'var(--t-red)' }}>
                      ${result.finalEquity.toLocaleString()}
                    </span>
                    <span className="text-xs font-mono block mt-1" style={{ color: 'var(--t-muted)' }}>Started with $1,000.00</span>
                  </div>
                  <button onClick={download}
                    className="flex items-center gap-2 px-4 py-2 text-xs font-mono transition-all"
                    style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
                    onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
                    onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
                    <Download size={12} /> DOWNLOAD JSON
                  </button>
                </div>
              </Panel>
            </>
          )}

          {!running && !result && (
            <div className="flex items-center justify-center h-64 t-card" style={{ borderStyle: 'dashed' }}>
              <div className="text-center">
                <span className="text-4xl font-mono" style={{ color: 'var(--t-border)' }}>[ ]</span>
                <p className="text-xs font-mono mt-3" style={{ color: 'var(--t-muted)' }}>configure and run to see results</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
