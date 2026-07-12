'use client';
import { useEffect, useRef, useState } from 'react';
import { useAeroStore, MainTab } from '@/lib/aeroStore';

type Phase = 'idle' | 'out' | 'in';

interface Props { children: (tab: MainTab) => React.ReactNode }

export function GlitchTransition({ children }: Props) {
  const { activeTab } = useAeroStore();
  const [visibleTab, setVisibleTab]   = useState<MainTab>(activeTab);
  const [phase, setPhase]             = useState<Phase>('idle');
  const pendingTab                    = useRef<MainTab>(activeTab);
  const timerRef                      = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (activeTab === visibleTab) return;
    pendingTab.current = activeTab;

    if (timerRef.current) clearTimeout(timerRef.current);

    // Phase 1: glitch-out the current content (180ms)
    setPhase('out');
    timerRef.current = setTimeout(() => {
      // Swap content while invisible
      setVisibleTab(pendingTab.current);
      // Phase 2: glitch-in the new content (220ms)
      setPhase('in');
      timerRef.current = setTimeout(() => {
        setPhase('idle');
      }, 240);
    }, 180);

    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [activeTab, visibleTab]);

  const cls =
    phase === 'out' ? 'content-glitch-out' :
    phase === 'in'  ? 'content-glitch-in'  : '';

  return (
    <>
      {/* Glitch flash overlay — rendered on top during transition */}
      {phase !== 'idle' && <GlitchOverlay />}

      <div key={visibleTab} className={cls} style={{ minHeight: '100%' }}>
        {children(visibleTab)}
      </div>
    </>
  );
}

// ── Overlay ──────────────────────────────────────────────────────────────────

function GlitchOverlay() {
  return (
    <div className="pointer-events-none fixed inset-0 z-[9998] overflow-hidden">
      {/* Cyan flash bar */}
      <div className="absolute inset-0"
        style={{ background: 'rgba(0,229,255,0.07)', animation: 'glitchFlash 0.38s steps(1,end) forwards' }} />
      {/* Red split bar */}
      <div className="absolute inset-x-0"
        style={{ top: '30%', height: '4px', background: 'rgba(255,59,92,0.5)', animation: 'glitchBars 0.38s steps(1,end) forwards', animationDelay: '20ms' }} />
      {/* Green split bar */}
      <div className="absolute inset-x-0"
        style={{ top: '65%', height: '2px', background: 'rgba(0,255,136,0.4)', animation: 'glitchBars 0.38s steps(1,end) forwards', animationDelay: '40ms' }} />
      {/* Cyan thin bar */}
      <div className="absolute inset-x-0"
        style={{ top: '15%', height: '1px', background: 'rgba(0,229,255,0.6)', animation: 'glitchBars 0.38s steps(1,end) forwards', animationDelay: '10ms' }} />
    </div>
  );
}
