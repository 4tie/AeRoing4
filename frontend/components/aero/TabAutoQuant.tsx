'use client';
import { useState, useEffect, useRef } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { Play, Loader2, BookOpen, AlertCircle, ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { getStrategyLibraryScan, startAeRoing4Run, getAeRoing4Run, type StrategyLibraryItem, type AeRoing4RunState } from '@/lib/api';

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
  const [currentRun, setCurrentRun] = useState<AeRoing4RunState | null>(null);
  const [expandedSection, setExpandedSection] = useState<string | null>(null);
  const [showAdvancedDiscovery, setShowAdvancedDiscovery] = useState(false);
  
  // DEVELOP run state
  const [isStartingDevelopRun, setIsStartingDevelopRun] = useState(false);
  const [developRunError, setDevelopRunError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  
  // Button ref for immediate DOM manipulation
  const developRunButtonRef = useRef<HTMLButtonElement>(null);
  
  // Ref for immediate duplicate-click prevention (synchronous)
  const isDevelopRunStartingRef = useRef(false);

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
    // Set loading state immediately to disable button
    setIsStartingDevelopRun(true);
    setValidationError(null);
    setDevelopRunError(null);

    // Prevent duplicate clicks using state
    if (isStartingDevelopRun || aering4Running) {
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      return;
    }

    // Validation
    if (!aering4StrategyName) {
      setValidationError('Please select a strategy');
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      return;
    }
    if (pairs.length === 0) {
      setValidationError('Select at least one pair before running a DEVELOP test.');
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      return;
    }
    if (!timeframe) {
      setDevelopRunError('Please select a timeframe');
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      return;
    }
    const timerange = getTimerange();
    if (!timerange) {
      setDevelopRunError('Please select a timerange');
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      return;
    }
    if (maxOpenTrades < 1) {
      setDevelopRunError('Max open trades must be at least 1');
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      return;
    }

    // Start DEVELOP run (no pair discovery)
    try {
      const initial = await startAeRoing4Run({
        strategy_name: aering4StrategyName,
        timeframe,
        smoke_timerange: timerange,
        smoke_pairs: pairs,
        max_open_trades: maxOpenTrades,
        dry_run_wallet: 1000,
        enable_pair_discovery: false,
        discovery_pairs: undefined,
        discovery_timerange: undefined,
      });

      setAering4Run(initial);
      setAering4Running(true);
      const runId = initial._runId;

      // Poll for run status
      const poll = async () => {
        try {
          const updated = await getAeRoing4Run(runId);
          setAering4Run(updated);
          setCurrentRun(updated);

          if (updated.status === 'running' || updated.status === 'pending') {
            pollRef.current = setTimeout(poll, 2000);
          } else {
            setAering4Running(false);
            setIsStartingDevelopRun(false);
            isDevelopRunStartingRef.current = false;
          }
        } catch (e) {
          setAering4Running(false);
          setIsStartingDevelopRun(false);
          isDevelopRunStartingRef.current = false;
          setDevelopRunError(e instanceof Error ? e.message : 'Polling failed');
        }
      };

      pollRef.current = setTimeout(poll, 2000);
    } catch (e) {
      setIsStartingDevelopRun(false);
      isDevelopRunStartingRef.current = false;
      setDevelopRunError(e instanceof Error ? e.message : 'Failed to start run');
    }
  };

  // Synchronous wrapper that uses ref for immediate duplicate-click prevention
  const handleRunDevelopTestSync = (e: React.MouseEvent) => {
    // IMMEDIATE synchronous check using ref (no React state updates)
    if (isDevelopRunStartingRef.current) {
      e.preventDefault();
      e.stopPropagation();
      return; // Already starting, ignore duplicate click
    }
    
    // Set ref immediately (synchronous, no React batching)
    isDevelopRunStartingRef.current = true;
    
    // Disable button immediately at DOM level
    if (developRunButtonRef.current) {
      developRunButtonRef.current.disabled = true;
    }
    
    // Prevent event propagation to stop other click handlers
    e.preventDefault();
    e.stopPropagation();
    
    // Call the async handler
    handleRunDevelopTest();
  };


  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="mb-6">
        <span className="t-label block mb-2">TAB 03 · AUTOQUANT</span>
        <h1 className="text-3xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>
          AutoQuant
        </h1>
        <span className="text-sm font-mono" style={{ color: 'var(--t-muted)' }}>
          Strategy validation and pair discovery workflow
        </span>
      </div>

      {/* Section 1: Strategy */}
      <div className="t-card">
        <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
          <span className="w-2 h-2 shrink-0" style={{ background: 'var(--t-cyan)' }} />
          <span className="text-sm font-bold" style={{ color: 'var(--t-text)' }}>1. STRATEGY</span>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <span className="text-sm font-semibold block mb-2" style={{ color: 'var(--t-text)' }}>Selected Strategy</span>
            <select 
              value={aering4StrategyName} 
              onChange={e => setAering4StrategyName(e.target.value)}
              className="w-full px-4 py-3 text-sm font-mono t-focus"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
            >
              <option value="">Select strategy...</option>
              {strategyNames.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {selectedStrategy && (
            <div className="p-4" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-mono font-bold" style={{ color: 'var(--t-cyan)' }}>
                  {selectedStrategy.strategy_name}
                </span>
                <button
                  onClick={() => setActiveTab('strategies')}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono transition-all"
                  style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}
                >
                  <BookOpen size={12} /> View in Library
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                <div><span style={{ color: 'var(--t-muted)' }}>Class:</span> {selectedStrategy.class_name || '-'}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Default Timeframe:</span> {selectedStrategy.timeframe || '-'}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Python Parameters:</span> {selectedStrategy.python_parameters.length}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Runtime Parameters:</span> {selectedStrategy.json_runtime_params.length}</div>
              </div>
              {selectedStrategy.timeframe && timeframe !== selectedStrategy.timeframe && (
                <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--t-border)' }}>
                  <div className="flex items-start gap-2" style={{ color: 'var(--t-yellow)' }}>
                    <AlertCircle size={14} className="shrink-0 mt-0.5" />
                    <div className="text-xs">
                      <span className="font-semibold">Selected timeframe differs from strategy default</span>
                      <div className="mt-1" style={{ color: 'var(--t-muted)' }}>
                        Strategy default: {selectedStrategy.timeframe} · Selected: {timeframe}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {selectedStrategy.warnings.length > 0 && (
                <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--t-border)' }}>
                  <div className="flex items-start gap-2" style={{ color: 'var(--t-yellow)' }}>
                    <AlertCircle size={14} className="shrink-0 mt-0.5" />
                    <div className="text-xs">
                      <span className="font-semibold">{selectedStrategy.warnings.length} warning{selectedStrategy.warnings.length > 1 ? 's' : ''}</span>
                      <div className="mt-1" style={{ color: 'var(--t-muted)' }}>
                        {selectedStrategy.warnings.map((w, i) => (
                          <div key={i}>• {w.message}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Section 2: Test Setup */}
      <div className="t-card">
        <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
          <span className="w-2 h-2 shrink-0" style={{ background: 'var(--t-cyan)' }} />
          <span className="text-sm font-bold" style={{ color: 'var(--t-text)' }}>2. TEST SETUP</span>
        </div>
        <div className="p-4 space-y-5">
          <div>
            <span className="text-sm font-semibold block mb-2" style={{ color: 'var(--t-text)' }}>Timeframe</span>
            <select 
              value={timeframe} 
              onChange={e => setTimeframe(e.target.value)}
              className="w-full px-4 py-3 text-sm font-mono t-focus"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
            >
              {TIMEFRAMES.map(tf => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>

          <div>
            <span className="text-sm font-semibold block mb-2" style={{ color: 'var(--t-text)' }}>Timerange</span>
            <select 
              value={timerangePreset} 
              onChange={e => setTimerangePreset(e.target.value)}
              className="w-full px-4 py-3 text-sm font-mono t-focus mb-3"
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
                className="w-full px-4 py-3 text-sm font-mono t-focus"
                style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} 
              />
            )}
            <div className="mt-2 text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
              Resolved: {getTimerange()}
            </div>
          </div>

          <div>
            <span className="text-sm font-semibold block mb-2" style={{ color: 'var(--t-text)' }}>Max Open Trades</span>
            <input 
              type="number" 
              value={maxOpenTrades} 
              onChange={e => setMaxOpenTrades(Number(e.target.value))}
              min={1}
              max={10}
              className="w-full px-4 py-3 text-sm font-mono t-focus"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} 
            />
          </div>

          <div>
            <span className="text-sm font-semibold block mb-2" style={{ color: 'var(--t-text)' }}>Pairs ({pairs.length} selected)</span>
            <div className="flex flex-wrap gap-2 mb-3">
              {ALL_PAIRS.map(p => (
                <button 
                  key={p} 
                  onClick={() => togglePair(p)}
                  className="px-3 py-1.5 text-xs font-mono transition-all"
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
            <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
              <span className="text-xs font-semibold" style={{ color: 'var(--t-text)' }}>Effective pairs for this run:</span>
              <div className="mt-1 text-sm font-mono" style={{ color: 'var(--t-cyan)' }}>
                {pairs.length > 0 ? pairs.join(', ') : 'None selected'}
              </div>
              {pairs.length > 1 && (
                <div className="mt-2 text-xs" style={{ color: 'var(--t-muted)' }}>
                  Note: Smoke backtest will run on all selected pairs. Pair discovery will evaluate the full discovery universe.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Section 3: Run Control */}
      <div className="t-card">
        <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
          <span className="w-2 h-2 shrink-0" style={{ background: 'var(--t-cyan)' }} />
          <span className="text-sm font-bold" style={{ color: 'var(--t-text)' }}>3. RUN CONTROL</span>
        </div>
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-3">
            <button
              ref={developRunButtonRef}
              disabled={!aering4StrategyName || pairs.length === 0 || aering4Running || isStartingDevelopRun}
              onClick={handleRunDevelopTestSync}
              className="flex items-center gap-2 px-6 py-3 font-semibold transition-all"
              style={{
                background: (!aering4StrategyName || pairs.length === 0 || aering4Running || isStartingDevelopRun) 
                  ? 'rgba(0,229,255,0.1)' 
                  : 'var(--t-cyan)',
                color: (!aering4StrategyName || pairs.length === 0 || aering4Running || isStartingDevelopRun) 
                  ? 'var(--t-muted)' 
                  : 'var(--t-bg)',
                border: '1px solid var(--t-border)',
                cursor: (!aering4StrategyName || pairs.length === 0 || aering4Running || isStartingDevelopRun) 
                  ? 'not-allowed' 
                  : 'pointer',
                opacity: (!aering4StrategyName || pairs.length === 0 || aering4Running || isStartingDevelopRun) ? 0.6 : 1
              }}
            >
              {isStartingDevelopRun ? (
                <Loader2 className="animate-spin" size={18} />
              ) : (
                <Play size={18} />
              )}
              {isStartingDevelopRun ? 'Starting...' : 'Run DEVELOP Test'}
            </button>

            <button
              onClick={() => {
                setPairs(['BTC/USDT','ETH/USDT']);
                setTimeframe('5m');
                setTimerangePreset('20230101-20240101');
                setTimerangeCustom('');
                setMaxOpenTrades(5);
                setDevelopRunError(null);
                setValidationError(null);
                setCurrentRun(null);
              }}
              className="px-4 py-3 font-semibold transition-all"
              style={{
                background: 'transparent',
                color: 'var(--t-label)',
                border: '1px solid var(--t-border)'
              }}
            >
              Reset
            </button>
          </div>

          {validationError && (
            <div className="flex items-start gap-2 p-3" style={{ background: 'rgba(255,100,100,0.1)', border: '1px solid var(--t-red)' }}>
              <XCircle size={16} className="shrink-0 mt-0.5" style={{ color: 'var(--t-red)' }} />
              <span className="text-sm" style={{ color: 'var(--t-red)' }}>{validationError}</span>
            </div>
          )}

          {developRunError && (
            <div className="flex items-start gap-2 p-3" style={{ background: 'rgba(255,100,100,0.1)', border: '1px solid var(--t-red)' }}>
              <XCircle size={16} className="shrink-0 mt-0.5" style={{ color: 'var(--t-red)' }} />
              <span className="text-sm" style={{ color: 'var(--t-red)' }}>{developRunError}</span>
            </div>
          )}

          {/* Advanced: Pair Discovery - Collapsed by default */}
          <div className="mt-4">
            <button
              onClick={() => setShowAdvancedDiscovery(!showAdvancedDiscovery)}
              className="flex items-center gap-2 text-xs font-mono transition-all"
              style={{ color: 'var(--t-muted)' }}
            >
              {showAdvancedDiscovery ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Advanced: Pair Discovery
            </button>
            {showAdvancedDiscovery && (
              <div className="mt-3 p-3" style={{ background: 'rgba(0,229,255,0.02)', border: '1px solid var(--t-border)' }}>
                <div className="text-xs" style={{ color: 'var(--t-muted)' }}>
                  Pair Discovery is an advanced workflow that evaluates multiple pairs across a discovery universe.
                  It runs automatically after a successful smoke backtest when enabled.
                </div>
                <div className="mt-2 text-xs font-mono" style={{ color: 'var(--t-label)' }}>
                  Current status: Disabled (DEVELOP mode uses selected pairs only)
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Section 4: Live Run Monitor */}
      {currentRun && (
        <div className="t-card">
          <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
            <span className="w-2 h-2 shrink-0" style={{ background: currentRun.status === 'running' ? 'var(--t-cyan)' : currentRun.status === 'done' ? 'var(--t-green)' : 'var(--t-red)' }} />
            <span className="text-sm font-bold" style={{ color: 'var(--t-text)' }}>4. LIVE RUN MONITOR</span>
            <span className="ml-auto text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
              {currentRun.status.toUpperCase()}
            </span>
          </div>
          <div className="p-4 space-y-3">
            {/* Run summary */}
            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div><span style={{ color: 'var(--t-muted)' }}>Run ID:</span> {currentRun.id.slice(0, 8)}...</div>
              <div><span style={{ color: 'var(--t-muted)' }}>Strategy:</span> {currentRun.strategy_name}</div>
              <div><span style={{ color: 'var(--t-muted)' }}>Timeframe:</span> {currentRun.strategy_timeframe}</div>
              <div><span style={{ color: 'var(--t-muted)' }}>Pairs:</span> {currentRun.smoke_pairs.join(', ')}</div>
            </div>

            {/* Workflow steps */}
            <div className="space-y-2">
              {currentRun.steps.map((step, idx) => (
                <div key={step.id}>
                  <button
                    onClick={() => setExpandedSection(expandedSection === step.id ? null : step.id)}
                    className="w-full px-3 py-2 flex items-center justify-between text-xs font-mono transition-all"
                    style={{ 
                      background: expandedSection === step.id ? 'rgba(0,229,255,0.05)' : 'transparent',
                      border: '1px solid var(--t-border)'
                    }}
                  >
                    <div className="flex items-center gap-2">
                      {step.status === 'done' && <CheckCircle2 size={14} style={{ color: 'var(--t-green)' }} />}
                      {step.status === 'running' && <Loader2 size={14} className="animate-spin" style={{ color: 'var(--t-cyan)' }} />}
                      {step.status === 'error' && <XCircle size={14} style={{ color: 'var(--t-red)' }} />}
                      {step.status === 'pending' && <Clock size={14} style={{ color: 'var(--t-muted)' }} />}
                      <span>{idx + 1}. {step.name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span style={{ color: 'var(--t-muted)' }}>{step.status.toUpperCase()}</span>
                      {expandedSection === step.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </div>
                  </button>
                  {expandedSection === step.id && (
                    <div className="px-3 py-2 text-xs font-mono" style={{ background: 'rgba(0,229,255,0.02)', border: '1px solid var(--t-border)', borderTop: 'none' }}>
                      <div className="space-y-1" style={{ color: 'var(--t-muted)' }}>
                        {step.logs.length > 0 && (
                          <div className="max-h-32 overflow-auto">
                            {step.logs.map((log, i) => (
                              <div key={i}>• {log}</div>
                            ))}
                          </div>
                        )}
                        {step.logs.length === 0 && <div>No logs available</div>}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Logs/details expandable */}
            <button
              onClick={() => setExpandedSection(expandedSection === 'logs' ? null : 'logs')}
              className="w-full px-3 py-2 flex items-center justify-between text-xs font-mono transition-all"
              style={{ border: '1px solid var(--t-border)', color: 'var(--t-muted)' }}
            >
              <span>View Full Logs & Details</span>
              {expandedSection === 'logs' ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
            {expandedSection === 'logs' && (
              <div className="px-3 py-2 text-xs font-mono space-y-2" style={{ background: 'rgba(0,229,255,0.02)', border: '1px solid var(--t-border)', borderTop: 'none' }}>
                <div><span style={{ color: 'var(--t-muted)' }}>Freqtrade Command:</span> {currentRun.freqtrade_command || 'N/A'}</div>
                <div><span style={{ color: 'var(--t-muted)' }}>Output Path:</span> {currentRun.output_result_path || 'N/A'}</div>
                {currentRun.log_excerpt && (
                  <div>
                    <span style={{ color: 'var(--t-muted)' }}>Log Excerpt:</span>
                    <pre className="mt-1 max-h-32 overflow-auto">{currentRun.log_excerpt}</pre>
                  </div>
                )}
                {currentRun.execution_error && (
                  <div style={{ color: 'var(--t-red)' }}>
                    <span style={{ color: 'var(--t-muted)' }}>Error:</span> {currentRun.execution_error}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Section 5: Results & Charts */}
      {currentRun && currentRun.status === 'done' && (
        <div className="t-card">
          <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
            <span className="w-2 h-2 shrink-0" style={{ background: 'var(--t-cyan)' }} />
            <span className="text-sm font-bold" style={{ color: 'var(--t-text)' }}>5. RESULTS & CHARTS</span>
          </div>
          <div className="p-4 space-y-4">
            {/* Outcome summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
                <div className="text-xs" style={{ color: 'var(--t-muted)' }}>Outcome</div>
                <div className="text-sm font-bold mt-1" style={{ color: 'var(--t-cyan)' }}>
                  {currentRun.outcome || 'Unknown'}
                </div>
              </div>
              <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
                <div className="text-xs" style={{ color: 'var(--t-muted)' }}>Total Trades</div>
                <div className="text-sm font-bold mt-1" style={{ color: 'var(--t-text)' }}>
                  {currentRun.total_trades ?? 0}
                </div>
              </div>
              <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
                <div className="text-xs" style={{ color: 'var(--t-muted)' }}>Profit Factor</div>
                <div className="text-sm font-bold mt-1" style={{ color: 'var(--t-text)' }}>
                  {currentRun.run_artifacts?.profit_factor ?? 'N/A'}
                </div>
              </div>
              <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
                <div className="text-xs" style={{ color: 'var(--t-muted)' }}>Max Drawdown</div>
                <div className="text-sm font-bold mt-1" style={{ color: 'var(--t-text)' }}>
                  {currentRun.run_artifacts?.max_drawdown ?? 'N/A'}
                </div>
              </div>
            </div>

            {/* No signal activity explanation */}
            {currentRun.outcome === 'NO_SIGNAL_ACTIVITY' && (
              <div className="p-4" style={{ background: 'rgba(255,200,0,0.05)', border: '1px solid var(--t-yellow)' }}>
                <div className="flex items-start gap-2">
                  <AlertCircle size={16} className="shrink-0 mt-0.5" style={{ color: 'var(--t-yellow)' }} />
                  <div className="text-sm">
                    <span className="font-semibold" style={{ color: 'var(--t-yellow)' }}>No Signal Activity</span>
                    <div className="mt-2" style={{ color: 'var(--t-muted)' }}>
                      The backtest completed successfully, but this strategy produced no trades for the selected pair, timeframe, and timerange.
                    </div>
                    <div className="mt-2 text-xs" style={{ color: 'var(--t-muted)' }}>
                      Try: longer timerange · different pair · strategy default timeframe · another strategy
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Pair discovery results */}
            {currentRun.discovery_result && currentRun.discovery_result.ranked_pairs && currentRun.discovery_result.ranked_pairs.length > 0 && (
              <div>
                <div className="text-sm font-semibold mb-2" style={{ color: 'var(--t-text)' }}>Pair Discovery Results</div>
                <div className="space-y-2">
                  {currentRun.discovery_result.ranked_pairs.slice(0, 5).map((pair: any, idx: number) => (
                    <div key={pair.pair} className="flex items-center justify-between p-2" style={{ background: 'rgba(0,229,255,0.02)', border: '1px solid var(--t-border)' }}>
                      <div className="text-xs font-mono">{idx + 1}. {pair.pair}</div>
                      <div className="text-xs font-mono" style={{ color: 'var(--t-cyan)' }}>Score: {pair.score?.toFixed(2)}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Section 6: Next Action */}
      {currentRun && currentRun.status === 'done' && (
        <div className="t-card">
          <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
            <span className="w-2 h-2 shrink-0" style={{ background: 'var(--t-cyan)' }} />
            <span className="text-sm font-bold" style={{ color: 'var(--t-text)' }}>6. NEXT ACTION</span>
          </div>
          <div className="p-4">
            {currentRun.outcome === 'NO_SIGNAL_ACTIVITY' && (
              <div className="flex items-start gap-3">
                <AlertCircle size={20} className="shrink-0 mt-0.5" style={{ color: 'var(--t-yellow)' }} />
                <div className="text-sm">
                  <span className="font-semibold" style={{ color: 'var(--t-text)' }}>Adjust Test Parameters</span>
                  <div className="mt-1" style={{ color: 'var(--t-muted)' }}>
                    Try a longer timerange, different pair, or the strategy&apos;s default timeframe.
                  </div>
                </div>
              </div>
            )}
            {currentRun.outcome === 'SUCCESS' && currentRun.total_trades && currentRun.total_trades > 0 && (
              <div className="flex items-start gap-3">
                <CheckCircle2 size={20} className="shrink-0 mt-0.5" style={{ color: 'var(--t-green)' }} />
                <div className="text-sm">
                  <span className="font-semibold" style={{ color: 'var(--t-text)' }}>Inspect Results</span>
                  <div className="mt-1" style={{ color: 'var(--t-muted)' }}>
                    Review the backtest metrics and trades in the Results tab.
                  </div>
                </div>
              </div>
            )}
            {currentRun.outcome === 'EXECUTION_FAILURE' && (
              <div className="flex items-start gap-3">
                <XCircle size={20} className="shrink-0 mt-0.5" style={{ color: 'var(--t-red)' }} />
                <div className="text-sm">
                  <span className="font-semibold" style={{ color: 'var(--t-text)' }}>Fix Validation Error</span>
                  <div className="mt-1" style={{ color: 'var(--t-muted)' }}>
                    Check the logs for the specific validation failure and fix the strategy or configuration.
                  </div>
                </div>
              </div>
            )}
            {!currentRun.outcome && (
              <div className="text-sm" style={{ color: 'var(--t-muted)' }}>
                Run completed. Check the Results tab for details.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
