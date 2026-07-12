'use client';

import React, { useState, useEffect } from 'react';
import { Clock, RefreshCw, AlertTriangle, ChevronDown, ChevronRight, Search, Filter } from 'lucide-react';
import { listAeRoing4Runs, getAutoQuantFlowForRun, type AeRoing4RunState, type AutoQuantFlowResponse } from '@/lib/api';

export function TabResults() {
  const [runs, setRuns] = useState<AeRoing4RunState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [candidateFlows, setCandidateFlows] = useState<Record<string, AutoQuantFlowResponse>>({});

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [strategyFilter, setStrategyFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');

  const loadRuns = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listAeRoing4Runs();
      setRuns(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Failed to load runs');
    } finally {
      setLoading(false);
    }
  };

  const loadCandidateFlow = async (runId: string) => {
    try {
      const flow = await getAutoQuantFlowForRun(runId);
      setCandidateFlows(prev => ({ ...prev, [runId]: flow }));
    } catch (exc) {
      console.error('Failed to load candidate flow:', exc);
    }
  };

  useEffect(() => {
    loadRuns();
  }, []);

  const toggleExpand = async (runId: string) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
    } else {
      setExpandedRunId(runId);
      if (!candidateFlows[runId]) {
        await loadCandidateFlow(runId);
      }
    }
  };

  // Filter runs
  const filteredRuns = runs.filter(run => {
    if (statusFilter !== 'all' && run.status !== statusFilter) return false;
    if (strategyFilter && !run.strategy_name.toLowerCase().includes(strategyFilter.toLowerCase())) return false;
    if (dateFrom) {
      const runDate = new Date(run.created_at);
      const filterDate = new Date(dateFrom);
      if (runDate < filterDate) return false;
    }
    return true;
  });

  // Format date
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const noSignalMessage = "The backtest completed successfully, but this strategy produced no trades for the selected pair, timeframe, and timerange. Try a longer timerange, another pair, or the strategy's default timeframe.";

  const displayStatus = (status: AeRoing4RunState['status']) => (
    status === 'done' ? 'completed' : status
  );

  const displayOutcome = (run: AeRoing4RunState) => {
    if (run.smoke_outcome === 'NO_SIGNAL_ACTIVITY' || run.outcome === 'NO_SIGNAL_ACTIVITY') return 'no_signal_activity';
    if (run.smoke_outcome === 'EXECUTION_FAILURE' || run.outcome === 'EXECUTION_FAILURE') return 'execution_failure';
    if (run.outcome === 'NO_PAIR_CANDIDATES') return 'no_pair_candidates';
    if (run.outcome === 'SUCCESS') return 'success';
    return run.outcome ? String(run.outcome).toLowerCase() : '-';
  };

  const displayPairs = (run: AeRoing4RunState) => {
    const pairs = run.smoke_pairs.length > 0 ? run.smoke_pairs : run.discovery_pairs;
    return pairs.length > 0 ? pairs.join(', ') : '-';
  };

  const displayTimerange = (run: AeRoing4RunState) => (
    run.smoke_timerange || run.discovery_timerange || '-'
  );

  const isNoSignalRun = (run: AeRoing4RunState) => (
    run.smoke_outcome === 'NO_SIGNAL_ACTIVITY' || run.outcome === 'NO_SIGNAL_ACTIVITY'
  );

  // Status badge colors
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'var(--t-yellow)';
      case 'running': return 'var(--t-cyan)';
      case 'done': return 'var(--t-green)';
      case 'error': return 'var(--t-red)';
      default: return 'var(--t-muted)';
    }
  };

  const statusCounts = {
    total: runs.length,
    running: runs.filter(r => r.status === 'running').length,
    done: runs.filter(r => r.status === 'done').length,
    error: runs.filter(r => r.status === 'error').length,
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 04 · RESULTS</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>
          Results & Runs
        </h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
          View backtest results and AutoQuant run history
        </span>
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-4 text-xs font-mono">
        <div style={{ color: 'var(--t-text)' }}>
          {statusCounts.total} runs total
        </div>
        <div style={{ color: 'var(--t-cyan)' }}>
          {statusCounts.running} running
        </div>
        <div style={{ color: 'var(--t-green)' }}>
          {statusCounts.done} completed
        </div>
        <div style={{ color: 'var(--t-red)' }}>
          {statusCounts.error} failed
        </div>
        <button
          onClick={loadRuns}
          className="flex items-center gap-1.5 px-2.5 py-1 transition-all"
          style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
          onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          REFRESH
        </button>
      </div>

      {/* Filters */}
      <div className="t-card p-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Filter size={12} style={{ color: 'var(--t-muted)' }} />
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="px-2 py-1 text-xs font-mono"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)' }}
            >
              <option value="all">All Status</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="done">Done</option>
              <option value="error">Error</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <Search size={12} style={{ color: 'var(--t-muted)' }} />
            <input
              type="text"
              value={strategyFilter}
              onChange={e => setStrategyFilter(e.target.value)}
              placeholder="Filter by strategy..."
              className="px-2 py-1 text-xs font-mono"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', width: '200px' }}
            />
          </div>
          <div className="flex items-center gap-2">
            <Clock size={12} style={{ color: 'var(--t-muted)' }} />
            <input
              type="date"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
              className="px-2 py-1 text-xs font-mono"
              style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)' }}
            />
          </div>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 t-card" style={{ borderColor: 'rgba(255,59,92,0.35)' }}>
          <div className="flex items-start gap-3">
            <AlertTriangle size={14} style={{ color: 'var(--t-red)', flexShrink: 0, marginTop: 2 }} />
            <div>
              <span className="text-xs font-mono block font-bold" style={{ color: 'var(--t-red)' }}>LOAD ERROR</span>
              <span className="text-xs font-mono block mt-1" style={{ color: 'var(--t-muted)' }}>{error}</span>
              <button
                onClick={loadRuns}
                className="mt-2 px-3 py-1 text-xs font-mono transition-all"
                style={{ border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)', background: 'rgba(0,229,255,0.06)' }}
              >
                RETRY
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && !error && (
        <div className="flex items-center justify-center h-40 t-card">
          <div className="text-center">
            <RefreshCw size={24} className="animate-spin" style={{ color: 'var(--t-cyan)', marginBottom: '1rem' }} />
            <p className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Loading runs...</p>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && filteredRuns.length === 0 && (
        <div className="flex items-center justify-center h-64 t-card" style={{ borderStyle: 'dashed' }}>
          <div className="text-center">
            <Clock size={32} style={{ color: 'var(--t-muted)', marginBottom: '1rem' }} />
            <p className="text-sm font-mono mb-2" style={{ color: 'var(--t-text)' }}>
              {runs.length === 0 ? 'No runs yet' : 'No runs match your filters'}
            </p>
            <p className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
              {runs.length === 0 ? 'Run a backtest or start AutoQuant to see results here.' : 'Try adjusting your filters.'}
            </p>
          </div>
        </div>
      )}

      {/* Runs table */}
      {!loading && !error && filteredRuns.length > 0 && (
        <div className="t-card overflow-hidden">
          <div className="px-3 py-2 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
            <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
            <span className="t-label">RUN HISTORY</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr style={{ background: 'var(--t-bg)', borderBottom: '1px solid var(--t-border)' }}>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>STATUS</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>STRATEGY</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>CREATED</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>TIMERANGE</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>TIMEFRAME</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>PAIRS</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}>DECISION</th>
                  <th className="px-3 py-2 text-left" style={{ color: 'var(--t-muted)' }}></th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.map((run) => (
                  <React.Fragment key={run.id}>
                    <tr
                      className="cursor-pointer transition-all hover:bg-opacity-50"
                      style={{ borderBottom: '1px solid var(--t-border)' }}
                      onClick={() => toggleExpand(run.id)}
                    >
                      <td className="px-3 py-2">
                        <span
                          className="px-2 py-0.5 text-[10px] font-bold uppercase"
                          style={{ background: `${getStatusColor(run.status)}20`, color: getStatusColor(run.status) }}
                        >
                          {displayStatus(run.status)}
                        </span>
                      </td>
                      <td className="px-3 py-2" style={{ color: 'var(--t-text)' }}>{run.strategy_name}</td>
                      <td className="px-3 py-2" style={{ color: 'var(--t-muted)' }}>{formatDate(run.created_at)}</td>
                      <td className="px-3 py-2" style={{ color: 'var(--t-muted)' }}>
                        {displayTimerange(run)}
                      </td>
                      <td className="px-3 py-2" style={{ color: 'var(--t-muted)' }}>{run.strategy_timeframe}</td>
                      <td className="px-3 py-2" style={{ color: 'var(--t-muted)' }}>
                        {displayPairs(run)}
                      </td>
                      <td className="px-3 py-2" style={{ color: 'var(--t-muted)' }}>
                        {isNoSignalRun(run) ? (
                          <span style={{ color: 'var(--t-yellow)' }}>NO SIGNAL</span>
                        ) : run.outcome === 'SUCCESS' ? (
                          <span style={{ color: 'var(--t-green)' }}>KEEP</span>
                        ) : run.outcome === 'NO_PAIR_CANDIDATES' ? (
                          <span style={{ color: 'var(--t-yellow)' }}>DROP</span>
                        ) : run.outcome === 'EXECUTION_FAILURE' ? (
                          <span style={{ color: 'var(--t-red)' }}>ERROR</span>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {expandedRunId === run.id ? (
                          <ChevronDown size={14} style={{ color: 'var(--t-muted)' }} />
                        ) : (
                          <ChevronRight size={14} style={{ color: 'var(--t-muted)' }} />
                        )}
                      </td>
                    </tr>
                    {expandedRunId === run.id && (
                      <tr>
                        <td colSpan={8} className="px-3 py-4" style={{ background: 'var(--t-bg)' }}>
                          <div className="space-y-3">
                            {/* Run details */}
                            <div>
                              <span className="t-label block mb-2">RUN DETAILS</span>
                              <div className="grid grid-cols-2 gap-2 text-xs">
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Run ID:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{run.id}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Created:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{new Date(run.created_at).toLocaleString()}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Status:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{displayStatus(run.status)}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Outcome:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{displayOutcome(run)}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Strategy:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{run.strategy_name || '-'}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Timeframe:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{run.strategy_timeframe || '-'}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Timerange:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{displayTimerange(run)}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Pair:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{displayPairs(run)}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Max Open Trades:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{run.max_open_trades ?? '-'}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Total Trades:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{run.total_trades ?? '-'}</span>
                                </div>
                                <div>
                                  <span style={{ color: 'var(--t-muted)' }}>Backtest Run ID:</span>
                                  <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{run.backtest_run_id ?? '-'}</span>
                                </div>
                              </div>
                              {isNoSignalRun(run) && (
                                <div className="mt-3 p-3 text-xs font-mono" style={{ background: 'rgba(255,184,0,0.06)', border: '1px solid rgba(255,184,0,0.25)', color: 'var(--t-yellow)' }}>
                                  {noSignalMessage}
                                </div>
                              )}
                            </div>

                            {/* Candidate flow */}
                            {candidateFlows[run.id]?.candidate && (() => {
                              const candidate = candidateFlows[run.id].candidate!;
                              return (
                                <div>
                                  <span className="t-label block mb-2">CANDIDATE FLOW</span>
                                  <div className="space-y-1 text-xs">
                                    <div>
                                      <span style={{ color: 'var(--t-muted)' }}>Decision:</span>
                                      <span style={{ color: 'var(--t-text)', marginLeft: '8px' }}>{candidate.decision ?? '-'}</span>
                                    </div>
                                    {candidate.reason_codes && candidate.reason_codes.length > 0 && (
                                      <div>
                                        <span style={{ color: 'var(--t-muted)' }}>Reason Codes:</span>
                                        <div className="mt-1 flex flex-wrap gap-1">
                                          {candidate.reason_codes.map((code, idx) => (
                                            <span
                                              key={idx}
                                              className="px-2 py-0.5"
                                              style={{ background: 'rgba(0,229,255,0.1)', color: 'var(--t-cyan)' }}
                                            >
                                              {code}
                                            </span>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    {candidate.candidate_directory && (
                                      <div>
                                        <span style={{ color: 'var(--t-muted)' }}>Candidate Path:</span>
                                        <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace' }}>
                                          {candidate.candidate_directory}
                                        </span>
                                      </div>
                                    )}
                                    {candidate.freqtrade_command && (
                                      <div>
                                        <span style={{ color: 'var(--t-muted)' }}>Freqtrade Command:</span>
                                        <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                          {candidate.freqtrade_command}
                                        </span>
                                      </div>
                                    )}
                                    {candidate.strategy_path_argument && (
                                      <div>
                                        <span style={{ color: 'var(--t-muted)' }}>--strategy-path:</span>
                                        <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                          {candidate.strategy_path_argument}
                                        </span>
                                      </div>
                                    )}
                                    {candidate.output_zip_path && (
                                      <div>
                                        <span style={{ color: 'var(--t-muted)' }}>Output Result:</span>
                                        <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                          {candidate.output_zip_path}
                                        </span>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              );
                            })()}

                            {(run.freqtrade_command || run.strategy_path_argument || run.output_result_path || run.output_zip_path || run.log_excerpt || run.execution_error) && (
                              <div>
                                <span className="t-label block mb-2">BACKTEST ARTIFACTS</span>
                                <div className="space-y-1 text-xs">
                                  {run.freqtrade_command && (
                                    <div>
                                      <span style={{ color: 'var(--t-muted)' }}>Freqtrade Command:</span>
                                      <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                        {run.freqtrade_command}
                                      </span>
                                    </div>
                                  )}
                                  {run.strategy_path_argument && (
                                    <div>
                                      <span style={{ color: 'var(--t-muted)' }}>--strategy-path:</span>
                                      <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                        {run.strategy_path_argument}
                                      </span>
                                    </div>
                                  )}
                                  {run.output_result_path && (
                                    <div>
                                      <span style={{ color: 'var(--t-muted)' }}>Output Result:</span>
                                      <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                        {run.output_result_path}
                                      </span>
                                    </div>
                                  )}
                                  {run.output_zip_path && (
                                    <div>
                                      <span style={{ color: 'var(--t-muted)' }}>Output Zip:</span>
                                      <span style={{ color: 'var(--t-text)', marginLeft: '8px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                        {run.output_zip_path}
                                      </span>
                                    </div>
                                  )}
                                  {run.execution_error && (
                                    <div style={{ color: 'var(--t-red)' }}>
                                      <span>Execution Error:</span>
                                      <span style={{ marginLeft: '8px' }}>{run.execution_error}</span>
                                    </div>
                                  )}
                                  {run.log_excerpt && (
                                    <pre className="mt-2 p-2 whitespace-pre-wrap overflow-auto" style={{ maxHeight: 180, background: '#050505', border: '1px solid var(--t-border)', color: 'var(--t-muted)' }}>
                                      {run.log_excerpt}
                                    </pre>
                                  )}
                                </div>
                              </div>
                            )}

                            {/* Steps */}
                            {run.steps && run.steps.length > 0 && (
                              <div>
                                <span className="t-label block mb-2">WORKFLOW STEPS</span>
                                <div className="space-y-1">
                                  {run.steps.map((step, idx) => (
                                    <div key={idx} className="flex items-center gap-2 text-xs">
                                      <span
                                        className="w-2 h-2 rounded-full"
                                        style={{
                                          background: step.status === 'done' ? 'var(--t-green)' :
                                                 step.status === 'running' ? 'var(--t-cyan)' :
                                                 step.status === 'error' ? 'var(--t-red)' : 'var(--t-muted)'
                                        }}
                                      />
                                      <span style={{ color: 'var(--t-text)' }}>{step.id}</span>
                                      <span style={{ color: 'var(--t-muted)' }}>-</span>
                                      <span style={{ color: 'var(--t-muted)' }}>{step.status}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
