'use client';
import { useEffect, useRef } from 'react';
import { useAeroStore, MainTab } from '@/lib/aeroStore';
import { getStrategies, checkBackendHealth } from '@/lib/api';
import { BookOpen, GraduationCap, Wrench, FlaskConical, Zap, Settings, Clock } from 'lucide-react';
import { GlitchLogo } from '@/components/aero/GlitchLogo';
import { StrategySpark } from '@/components/aero/StrategySpark';

const TABS: { id: MainTab; label: string; sub: string; num: string; icon: React.ReactNode }[] = [
  { id: 'read',      label: 'Read',      sub: 'Understand the code',  num: '1', icon: <BookOpen size={13} /> },
  { id: 'learn',     label: 'Learn',     sub: 'AI teaches you',       num: '2', icon: <GraduationCap size={13} /> },
  { id: 'fix',       label: 'Fix',       sub: 'Auto-improve',         num: '3', icon: <Wrench size={13} /> },
  { id: 'test',      label: 'Test',      sub: 'Backtest verdict',     num: '4', icon: <FlaskConical size={13} /> },
  { id: 'autoquant', label: 'AutoQuant', sub: 'Pipeline engine',      num: '5', icon: <Zap size={13} /> },
  { id: 'settings',  label: 'Settings',  sub: 'Configure',            num: '6', icon: <Settings size={13} /> },
];

export function AeroLayout({ children }: { children: React.ReactNode }) {
  const { activeTab, setActiveTab, strategies, setStrategies, selectedStrategyName, setSelectedStrategyName, backendConnected, setBackendConnected, setBackendStatus } = useAeroStore();
  const tabRefs = useRef<Map<MainTab, HTMLButtonElement>>(new Map());

  useEffect(() => {
    getStrategies().then((strats) => {
      setStrategies(strats);
      // Auto-select the first strategy if nothing is selected yet
      if (strats.length > 0) {
        const { selectedStrategyName: current, setSelectedStrategyName, setAering4StrategyName } = useAeroStore.getState();
        if (!current || !strats.find((s) => s.name === current)) {
          setSelectedStrategyName(strats[0].name);
          setAering4StrategyName(strats[0].name);
        }
      }
    });
  }, [setStrategies]);

  useEffect(() => {
    const check = async () => {
      const h = await checkBackendHealth();
      setBackendConnected(h.ok);
      setBackendStatus(h.ok ? 'CONNECTED' : 'OFFLINE');
    };
    check();
    const id = setInterval(check, 5000);
    return () => clearInterval(id);
  }, [setBackendConnected, setBackendStatus]);

  const handleTabClick = (tabId: MainTab) => {
    if (tabId === activeTab) return;
    // Fire burst class on the clicked button, then switch
    const btn = tabRefs.current.get(tabId);
    if (btn) {
      btn.classList.remove('tab-glitch-burst');
      // Force reflow so removing + re-adding triggers the animation
      void btn.offsetWidth;
      btn.classList.add('tab-glitch-burst');
      btn.addEventListener('animationend', () => btn.classList.remove('tab-glitch-burst'), { once: true });
    }
    setActiveTab(tabId);
  };

  const showStrategySidebar = activeTab === 'read' || activeTab === 'learn' || activeTab === 'fix';

  return (
    <div className="scanlines min-h-screen flex flex-col" style={{ background: 'var(--t-bg)', color: 'var(--t-text)', fontFamily: 'inherit' }}>

      {/* ── Top Nav ── */}
      <nav style={{ background: 'var(--t-surface)', borderBottom: '1px solid var(--t-border)' }}
        className="h-12 flex items-center px-4 gap-0 shrink-0 sticky top-0 z-50">

        {/* Logo — glitch effect */}
        <GlitchLogo />

        {/* Tab strip — equal-width, fills remaining space */}
        <div className="flex items-stretch h-full flex-1 min-w-0">
          {TABS.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                ref={el => { if (el) tabRefs.current.set(tab.id, el); else tabRefs.current.delete(tab.id); }}
                onClick={() => handleTabClick(tab.id)}
                className="flex flex-col items-center justify-center flex-1 min-w-0 h-full transition-all relative"
                style={{
                  borderRight: '1px solid var(--t-border)',
                  background: active ? 'rgba(0,229,255,0.06)' : 'transparent',
                  borderBottom: active ? '2px solid var(--t-cyan)' : '2px solid transparent',
                  paddingBottom: active ? 0 : 2,
                }}
              >
                <span style={{ color: active ? 'var(--t-cyan)' : 'var(--t-muted)' }}>{tab.icon}</span>
                <span className="text-[10px] font-mono font-semibold mt-0.5 truncate px-1 w-full text-center"
                  style={{ color: active ? 'var(--t-cyan)' : 'var(--t-label)' }}>
                  {tab.label}
                </span>
              </button>
            );
          })}
        </div>

        {/* Status */}
        <div className="flex items-center gap-1.5 ml-2 pl-2 shrink-0" style={{ borderLeft: '1px solid var(--t-border)' }}>
          <span className="w-1.5 h-1.5" style={{ background: backendConnected ? 'var(--t-green)' : 'var(--t-red)', boxShadow: backendConnected ? '0 0 6px var(--t-green)' : '0 0 6px var(--t-red)' }} />
          <span className="text-[10px] font-mono hidden sm:block" style={{ color: backendConnected ? 'var(--t-green)' : 'var(--t-red)' }}>{backendConnected ? 'LIVE' : 'OFFLINE'}</span>
        </div>
      </nav>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Sidebar */}
        {showStrategySidebar && (
          <aside className="w-52 shrink-0 overflow-y-auto hidden md:flex flex-col"
            style={{ background: 'var(--t-surface)', borderRight: '1px solid var(--t-border)' }}>
            <div className="px-3 py-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
              <span className="t-label">{'// STRATEGIES'}</span>
            </div>
            <div className="flex-1 p-2 space-y-1">
              {strategies.map((s) => {
                const sel = selectedStrategyName === s.name;
                return (
                  <button key={s.name} onClick={() => setSelectedStrategyName(s.name)}
                    className="w-full text-left p-2 transition-all"
                    style={{
                      background: sel ? 'rgba(0,229,255,0.06)' : 'transparent',
                      border: `1px solid ${sel ? 'var(--t-border-hi)' : 'transparent'}`,
                      boxShadow: sel ? 'inset 2px 0 0 var(--t-cyan)' : 'none',
                    }}
                  >
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <span className="w-1 h-1 shrink-0" style={{ background: sel ? 'var(--t-cyan)' : 'var(--t-muted)' }} />
                      <span className="text-[11px] font-mono truncate leading-tight" style={{ color: sel ? 'var(--t-cyan)' : 'var(--t-text)' }}>
                        {s.name}
                      </span>
                    </div>
                    <div className="flex items-end justify-between pl-2.5">
                      <StrategySpark name={s.name} selected={sel} width={68} height={22} />
                      <span className="text-[9px] font-mono shrink-0 ml-1" style={{ color: s.stoploss >= -0.1 ? 'var(--t-green)' : 'var(--t-yellow)' }}>
                        SL {(s.stoploss * 100).toFixed(0)}%
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
            {/* Sidebar footer */}
            <div className="px-3 py-2" style={{ borderTop: '1px solid var(--t-border)' }}>
              <span className="text-[10px] font-mono" style={{ color: 'var(--t-muted)' }}>{strategies.length} strategies loaded</span>
            </div>
          </aside>
        )}

        {/* Test run history sidebar */}
        {activeTab === 'test' && (
          <aside className="w-44 shrink-0 hidden md:flex flex-col"
            style={{ background: 'var(--t-surface)', borderRight: '1px solid var(--t-border)' }}>
            <div className="px-3 py-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
              <span className="t-label">{'// RUN HISTORY'}</span>
            </div>
            <div className="flex-1 p-2 space-y-1">
              <div className="text-xs font-mono py-8 text-center" style={{ color: 'var(--t-muted)' }}>
                No run history available yet
              </div>
            </div>
          </aside>
        )}

        {/* Main */}
        <main className="flex-1 overflow-y-auto p-5">
          {children}
        </main>
      </div>
    </div>
  );
}
