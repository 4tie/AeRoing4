'use client';
import { useState, useEffect } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { Play, Loader2, BookOpen } from 'lucide-react';
import { AeRoing4Panel } from '@/components/aero/AeRoing4Panel';
import { getStrategyLibraryScan, type StrategyLibraryItem } from '@/lib/api';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

const TIMERANGE_PRESETS = [
  { label: '7 days', value: '20240101-20240108' },
  { label: '30 days', value: '20231202-20240101' },
  { label: '3 months', value: '20231001-20240101' },
  { label: '6 months', value: '20230701-20240101' },
  { label: '1 year', value: '20230101-20240101' },
  { label: 'Custom', value: '' },
];

const ALL_PAIRS = [
  'BTC/USDT','ETH/USDT','BNB/USDT','SOL/USDT','ADA/USDT','AVAX/USDT','DOT/USDT','MATIC/USDT',
  'LINK/USDT','UNI/USDT','ATOM/USDT','LTC/USDT','XRP/USDT','DOGE/USDT','NEAR/USDT','APE/USDT'
];

export function TabAutoQuant() {
  const { strategies, aering4StrategyName, setAering4StrategyName, setActiveTab } = useAeroStore();
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyLibraryItem | null>(null);
  const [timeframe, setTimeframe] = useState('5m');
  const [timerangePreset, setTimerangePreset] = useState('20230101-20240101');
  const [timerangeCustom, setTimerangeCustom] = useState('');
  const [maxOpenTrades, setMaxOpenTrades] = useState(5);
  const [pairs, setPairs] = useState(['BTC/USDT','ETH/USDT']);
  const [loading] = useState(false);

  // Load selected strategy details
  useEffect(() => {
    if (!aering4StrategyName) return;
    getStrategyLibraryScan().then(scan => {
      const strat = scan?.strategies.find(s => s.strategy_name === aering4StrategyName);
      setSelectedStrategy(strat ?? null);
    }).catch(() => {});
  }, [aering4StrategyName]);

  const togglePair = (p: string) => setPairs(prev => prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]);

  const strategyNames = strategies.map(s => s.name);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 03 · AUTOQUANT</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>
          AutoQuant
        </h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
          Run strategy validation and discovery tests
        </span>
      </div>

      {/* Step 1: Select Strategy */}
      <div className="t-card">
        <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
          <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
          <span className="t-label">STEP 1 · SELECT STRATEGY</span>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <span className="t-label block mb-1.5">STRATEGY</span>
            <select 
              value={aering4StrategyName} 
              onChange={e => setAering4StrategyName(e.target.value)}
              className="w-full px-3 py-2 text-xs font-mono t-focus"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
            >
              <option value="">Select strategy...</option>
              {strategyNames.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {selectedStrategy && (
            <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono font-bold" style={{ color: 'var(--t-cyan)' }}>
                  {selectedStrategy.strategy_name}
                </span>
                <button
                  onClick={() => setActiveTab('strategies')}
                  className="flex items-center gap-1.5 px-2 py-1 text-[10px] font-mono transition-all"
                  style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}
                >
                  <BookOpen size={10} /> VIEW IN LIBRARY
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                <div><span style={{ color: 'var(--t-muted)' }}>Class:</span> {selectedStrategy.class_name || '-'}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Timeframe:</span> {selectedStrategy.timeframe || '-'}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Python params:</span> {selectedStrategy.python_parameters.length}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Runtime params:</span> {selectedStrategy.json_runtime_params.length}</div>
              </div>
              {selectedStrategy.warnings.length > 0 && (
                <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--t-border)' }}>
                  <span className="text-[10px] font-mono" style={{ color: 'var(--t-yellow)' }}>
                    {selectedStrategy.warnings.length} warning{selectedStrategy.warnings.length > 1 ? 's' : ''}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Step 2: Configure Test */}
      <div className="t-card">
        <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
          <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
          <span className="t-label">STEP 2 · CONFIGURE TEST</span>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <span className="t-label block mb-1.5">TIMEFRAME</span>
            <select 
              value={timeframe} 
              onChange={e => setTimeframe(e.target.value)}
              className="w-full px-3 py-2 text-xs font-mono t-focus"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
            >
              {TIMEFRAMES.map(tf => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>

          <div>
            <span className="t-label block mb-1.5">TIMERANGE</span>
            <select 
              value={timerangePreset} 
              onChange={e => setTimerangePreset(e.target.value)}
              className="w-full px-3 py-2 text-xs font-mono t-focus mb-2"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
            >
              {TIMERANGE_PRESETS.map(preset => (
                <option key={preset.value} value={preset.value}>{preset.label}</option>
              ))}
            </select>
            {!timerangePreset && (
              <input 
                type="text" 
                value={timerangeCustom} 
                onChange={e => setTimerangeCustom(e.target.value)}
                placeholder="YYYYMMDD-YYYYMMDD"
                className="w-full px-3 py-2 text-xs font-mono t-focus"
                style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} 
              />
            )}
          </div>

          <div>
            <span className="t-label block mb-1.5">MAX OPEN TRADES</span>
            <input 
              type="number" 
              value={maxOpenTrades} 
              onChange={e => setMaxOpenTrades(Number(e.target.value))}
              min={1}
              max={10}
              className="w-full px-3 py-2 text-xs font-mono t-focus"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} 
            />
          </div>

          <div>
            <span className="t-label block mb-1.5">PAIRS ({pairs.length} selected)</span>
            <div className="flex flex-wrap gap-1.5">
              {ALL_PAIRS.map(p => (
                <button 
                  key={p} 
                  onClick={() => togglePair(p)}
                  className="px-2 py-1 text-[10px] font-mono transition-all"
                  style={{ 
                    border: `1px solid ${pairs.includes(p) ? 'var(--t-border-hi)' : 'var(--t-border)'}`, 
                    background: pairs.includes(p) ? 'rgba(0,229,255,0.08)' : 'transparent', 
                    color: pairs.includes(p) ? 'var(--t-cyan)' : 'var(--t-label)' 
                  }}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Step 3: Run */}
      <div className="flex items-center gap-3">
        <button 
          disabled={!aering4StrategyName || pairs.length === 0}
          className="flex items-center gap-2 px-5 py-2.5 text-sm font-mono font-bold transition-all disabled:opacity-40"
          style={{ background: 'rgba(0,229,255,0.08)', border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)' }}
          onMouseEnter={e => !loading && (e.currentTarget.style.background = 'rgba(0,229,255,0.15)')}
          onMouseLeave={e => !loading && (e.currentTarget.style.background = 'rgba(0,229,255,0.08)')}
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {loading ? 'RUNNING...' : 'RUN DEVELOP TEST'}
        </button>
        <button 
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-mono transition-all"
          style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
          onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}
        >
          RESET
        </button>
      </div>

      {/* Step 4: Current Flow - AeRoing4 Panel */}
      <AeRoing4Panel />
    </div>
  );
}
