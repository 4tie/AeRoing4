'use client';
import { useState, useEffect, useRef } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { Play, Loader2, BookOpen, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';
import { AeRoing4Panel } from '@/components/aero/AeRoing4Panel';
import { getStrategyLibraryScan, startAeRoing4Run, getAeRoing4Run, type StrategyLibraryItem } from '@/lib/api';

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
  const { strategies, aering4StrategyName, setAering4StrategyName, setActiveTab, aering4Running, setAering4Run, setAering4Running } = useAeroStore();
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyLibraryItem | null>(null);
  const [timeframe, setTimeframe] = useState('5m');
  const [timerangePreset, setTimerangePreset] = useState('20230101-20240101');
  const [timerangeCustom, setTimerangeCustom] = useState('');
  const [maxOpenTrades, setMaxOpenTrades] = useState(5);
  const [pairs, setPairs] = useState(['BTC/USDT','ETH/USDT']);
  
  // DEVELOP run state
  const [isStartingDevelopRun, setIsStartingDevelopRun] = useState(false);
  const [developRunError, setDevelopRunError] = useState<string | null>(null);
  const [developRunDebug, setDevelopRunDebug] = useState<Record<string, unknown> | null>(null);
  const [showDebug, setShowDebug] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load selected strategy details
  useEffect(() => {
    if (!aering4StrategyName) return;
    getStrategyLibraryScan().then(scan => {
      const strat = scan?.strategies.find(s => s.strategy_name === aering4StrategyName);
      setSelectedStrategy(strat ?? null);
    }).catch(() => {
      // Silently fail - strategy details are optional
    });
  }, [aering4StrategyName]);

  const togglePair = (p: string) => setPairs(prev => prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]);

  const strategyNames = strategies.map(s => s.name);

  // Get actual timerange value (preset or custom)
  const getTimerange = () => {
    if (timerangePreset) return timerangePreset;
    return timerangeCustom || '20240101-20240108';
  };

  // Handle RUN DEVELOP TEST button click
  const handleRunDevelopTest = async () => {
    // Validation
    if (!aering4StrategyName) {
      setDevelopRunError('Please select a strategy');
      return;
    }
    if (pairs.length === 0) {
      setDevelopRunError('Please select at least one pair');
      return;
    }
    if (!timeframe) {
      setDevelopRunError('Please select a timeframe');
      return;
    }
    const timerange = getTimerange();
    if (!timerange) {
      setDevelopRunError('Please select a timerange');
      return;
    }
    if (maxOpenTrades < 1) {
      setDevelopRunError('Max open trades must be at least 1');
      return;
    }

    // Prevent duplicate clicks
    if (isStartingDevelopRun || aering4Running) return;

    setIsStartingDevelopRun(true);
    setDevelopRunError(null);
    setDevelopRunDebug({
      endpoint: '/api/aeroing4/runs',
      method: 'POST',
      strategy: aering4StrategyName,
      timeframe,
      timerange,
      pairs,
      maxOpenTrades,
      mode: 'DEVELOP',
      enable_pair_discovery: false,
    });

    try {
      // Start DEVELOP run (no pair discovery)
      const initial = await startAeRoing4Run({
        strategy_name: aering4StrategyName,
        timeframe,
        smoke_timerange: timerange,
        smoke_pairs: pairs,
        enable_pair_discovery: false, // Key difference: no discovery
        discovery_pairs: undefined,
        discovery_timerange: undefined,
      });

      setAering4Run(initial);
      setAering4Running(true);
      const runId = initial._runId;

      setDevelopRunDebug(prev => ({
        ...prev,
        run_id: runId,
        status: 'started',
      }));

      // Poll for run status
      const poll = async () => {
        try {
          const updated = await getAeRoing4Run(runId);
          setAering4Run(updated);
          setDevelopRunDebug(prev => ({
            ...prev,
            current_status: updated.status,
            outcome: updated.outcome,
          }));

          if (updated.status === 'running' || updated.status === 'pending') {
            pollRef.current = setTimeout(poll, 2000);
          } else {
            setAering4Running(false);
            setIsStartingDevelopRun(false);
          }
        } catch (e) {
          setAering4Running(false);
          setIsStartingDevelopRun(false);
          setDevelopRunError(e instanceof Error ? e.message : 'Polling failed');
        }
      };

      pollRef.current = setTimeout(poll, 2000);
    } catch (e) {
      setIsStartingDevelopRun(false);
      setDevelopRunError(e instanceof Error ? e.message : 'Failed to start run');
      setDevelopRunDebug(prev => ({
        ...prev,
        error: e instanceof Error ? e.message : 'Unknown error',
      }));
    }
  };

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

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
          disabled={!aering4StrategyName || pairs.length === 0 || aering4Running || isStartingDevelopRun}
          onClick={handleRunDevelopTest}
          className="flex items-center gap-2 px-5 py-2.5 text-sm font-mono font-bold transition-all disabled:opacity-40"
          style={{ background: 'rgba(0,229,255,0.08)', border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)' }}
          onMouseEnter={e => !aering4Running && !isStartingDevelopRun && (e.currentTarget.style.background = 'rgba(0,229,255,0.15)')}
          onMouseLeave={e => !aering4Running && !isStartingDevelopRun && (e.currentTarget.style.background = 'rgba(0,229,255,0.08)')}
        >
          {isStartingDevelopRun || aering4Running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {isStartingDevelopRun ? 'STARTING...' : aering4Running ? 'RUNNING...' : 'RUN DEVELOP TEST'}
        </button>
        <button 
          onClick={() => {
            setPairs(['BTC/USDT','ETH/USDT']);
            setTimeframe('5m');
            setTimerangePreset('20230101-20240101');
            setTimerangeCustom('');
            setMaxOpenTrades(5);
            setDevelopRunError(null);
            setDevelopRunDebug(null);
          }}
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-mono transition-all"
          style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
          onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}
        >
          RESET
        </button>
      </div>

      {/* Error message */}
      {developRunError && (
        <div className="px-4 py-2 text-xs font-mono flex items-center gap-2" style={{ background: 'rgba(255,59,92,0.06)', border: '1px solid rgba(255,59,92,0.3)', color: 'var(--t-red)' }}>
          <AlertCircle size={12} />
          {developRunError}
        </div>
      )}

      {/* Debug details */}
      {developRunDebug && (
        <div className="t-card">
          <button 
            onClick={() => setShowDebug(!showDebug)}
            className="w-full px-3 py-2 flex items-center justify-between text-xs font-mono"
            style={{ color: 'var(--t-muted)' }}
          >
            <span>DEBUG DETAILS</span>
            {showDebug ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
          {showDebug && (
            <div className="px-3 pb-3 text-[10px] font-mono space-y-1" style={{ color: 'var(--t-muted)' }}>
              <div>Endpoint: {developRunDebug.endpoint as string}</div>
              <div>Method: {developRunDebug.method as string}</div>
              <div>Strategy: {developRunDebug.strategy as string}</div>
              <div>Timeframe: {developRunDebug.timeframe as string}</div>
              <div>Timerange: {developRunDebug.timerange as string}</div>
              <div>Pairs: {(developRunDebug.pairs as string[]).join(', ')}</div>
              <div>Max Open Trades: {developRunDebug.maxOpenTrades as number}</div>
              <div>Mode: {developRunDebug.mode as string}</div>
              <div>Pair Discovery: {developRunDebug.enable_pair_discovery ? 'enabled' : 'disabled'}</div>
              {developRunDebug.run_id && <div>Run ID: {String(developRunDebug.run_id)}</div>}
              {developRunDebug.current_status && <div>Status: {String(developRunDebug.current_status)}</div>}
              {developRunDebug.outcome && <div>Outcome: {String(developRunDebug.outcome)}</div>}
              {developRunDebug.error && <div style={{ color: 'var(--t-red)' }}>Error: {String(developRunDebug.error)}</div>}
            </div>
          )}
        </div>
      )}

      {/* Step 4: Current Flow - AeRoing4 Panel */}
      <AeRoing4Panel />
    </div>
  );
}
