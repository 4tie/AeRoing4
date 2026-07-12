'use client';

import { useState, useEffect } from 'react';
import { Search, FileCode2, AlertTriangle } from 'lucide-react';
import { StrategyLibraryTable } from '@/components/aero/StrategyLibraryView';
import { getStrategyLibraryScan, type StrategyLibraryScan } from '@/lib/api';

export function TabStrategies() {
  const [searchQuery, setSearchQuery] = useState('');
  const [scan, setScan] = useState<StrategyLibraryScan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadLibrary = async () => {
    try {
      const data = await getStrategyLibraryScan();
      setScan(data);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Failed to load strategy library');
    }
  };

  // Load strategy library data on mount
  useEffect(() => {
    loadLibrary();
  }, []);

  const filteredStrategies = scan?.strategies.filter(s => 
    s.strategy_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.class_name?.toLowerCase().includes(searchQuery.toLowerCase())
  ) ?? [];

  const warningCount = filteredStrategies.reduce((count, item) => count + item.warnings.length, 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 02 · STRATEGY LIBRARY</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>
          Strategy Library
        </h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
          Browse and manage your trading strategies from user_data/strategies
        </span>
      </div>

      {/* Search bar */}
      <div className="t-card p-3">
        <div className="flex items-center gap-2">
          <Search size={14} style={{ color: 'var(--t-muted)' }} />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search strategies by name or class..."
            className="flex-1 px-3 py-2 text-xs font-mono t-focus"
            style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }}
          />
        </div>
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-3 text-xs font-mono">
        <div className="flex items-center gap-1.5">
          <FileCode2 size={13} style={{ color: 'var(--t-cyan)' }} />
          <span style={{ color: 'var(--t-text)' }}>{filteredStrategies.length} strategies</span>
        </div>
        <div className="flex items-center gap-1.5">
          <AlertTriangle size={13} style={{ color: warningCount ? 'var(--t-yellow)' : 'var(--t-green)' }} />
          <span style={{ color: warningCount ? 'var(--t-yellow)' : 'var(--t-green)' }}>{warningCount} warnings</span>
        </div>
        {scan && (
          <span style={{ color: 'var(--t-muted)' }}>
            Source: {scan.strategies_dir}
          </span>
        )}
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
                
onClick={loadLibrary}
                className="mt-2 px-3 py-1 text-xs font-mono transition-all"
                style={{ border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)', background: 'rgba(0,229,255,0.06)' }}
              >
                RETRY
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Strategy Library Table */}
      {scan && (
        <StrategyLibraryTable 
          scan={{ ...scan, strategies: filteredStrategies }} 
          error={error} 
        />
      )}

      {/* Empty state */}
      {!error && (!scan || filteredStrategies.length === 0) && (
        <div className="flex items-center justify-center h-40 t-card" style={{ borderStyle: 'dashed' }}>
          <div className="text-center">
            <p className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>
              {searchQuery ? 'No strategies match your search.' : 'No strategy files found.'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
