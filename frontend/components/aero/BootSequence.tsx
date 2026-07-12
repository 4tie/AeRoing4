'use client';
import { useEffect, useRef, useState } from 'react';

const DIM   = '#444';
const CYAN  = '#00E5FF';
const GREEN = '#00FF88';
const RED   = '#FF3B5C';
const AMBER = '#FFB800';

// Each line: text to type, optional color override, optional pre-line pause (ms)
const BOOT_LINES: { text: string; color?: string; delay?: number }[] = [
  { text: 'AERO STRATEGY TERMINAL · V0.1',           color: CYAN,  delay: 0   },
  { text: '──────────────────────────────────────',  color: DIM,   delay: 80  },
  { text: 'Initializing kernel modules...',           color: DIM,   delay: 60  },
  { text: '[  OK  ] Loaded freqtrade adapter',        color: GREEN, delay: 40  },
  { text: '[  OK  ] Mounted strategy filesystem',     color: GREEN, delay: 30  },
  { text: '[  OK  ] Connected to data feed',          color: GREEN, delay: 30  },
  { text: '[ WARN ] No live exchange credentials',    color: AMBER, delay: 40  },
  { text: '[  OK  ] Mock API layer active',           color: GREEN, delay: 20  },
  { text: '──────────────────────────────────────',  color: DIM,   delay: 80  },
  { text: 'Loading strategy index...',                color: DIM,   delay: 50  },
  { text: '  ▸ Connecting to strategy registry...',  color: DIM,   delay: 30  },
  { text: '  ▸ Scanning user_data/strategies/',      color: CYAN,  delay: 20  },
  { text: 'Strategies loaded from backend.',          color: GREEN, delay: 60  },
  { text: '──────────────────────────────────────',  color: DIM,   delay: 60  },
  { text: 'Running pre-flight checks...',             color: DIM,   delay: 40  },
  { text: '  backtest engine      ........  PASS',   color: GREEN, delay: 30  },
  { text: '  hyperopt pipeline    ........  PASS',   color: GREEN, delay: 25  },
  { text: '  overfit detector     ........  PASS',   color: GREEN, delay: 25  },
  { text: '  risk scoring module  ........  PASS',   color: GREEN, delay: 25  },
  { text: '  live feed            ........  SKIP',   color: RED,   delay: 30  },
  { text: '──────────────────────────────────────',  color: DIM,   delay: 80  },
  { text: 'System ready. Launching dashboard...',     color: CYAN,  delay: 60  },
];

interface Props { onDone: () => void }

export function BootSequence({ onDone }: Props) {
  const [visibleLines, setVisibleLines] = useState<typeof BOOT_LINES>([]);
  const [currentText, setCurrentText] = useState('');
  const [lineIdx, setLineIdx] = useState(0);
  const [charIdx, setCharIdx] = useState(0);
  const [done, setDone] = useState(false);
  const [fadeOut, setFadeOut] = useState(false);
  const termRef = useRef<HTMLDivElement>(null);
  const rafRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-scroll terminal window as lines appear
  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [visibleLines, currentText]);

  // Core typewriter loop
  useEffect(() => {
    if (lineIdx >= BOOT_LINES.length) {
      // All lines done → fade out then call onDone
      rafRef.current = setTimeout(() => {
        setFadeOut(true);
        setTimeout(() => { setDone(true); onDone(); }, 650);
      }, 400);
      return;
    }

    const line = BOOT_LINES[lineIdx];
    const preDelay = charIdx === 0 ? (line.delay ?? 40) : 0;

    rafRef.current = setTimeout(() => {
      if (charIdx < line.text.length) {
        // Type next character — separator lines appear instantly
        const isSep = line.text.startsWith('──');
        const next  = isSep ? line.text.length : charIdx + 1;
        setCurrentText(line.text.slice(0, next));
        setCharIdx(next);
      } else {
        // Line complete — commit it, move to next
        setVisibleLines(prev => [...prev, line]);
        setCurrentText('');
        setCharIdx(0);
        setLineIdx(prev => prev + 1);
      }
    }, charIdx === 0 ? preDelay : (line.text.startsWith('──') ? 0 : 18));

    return () => { if (rafRef.current) clearTimeout(rafRef.current); };
  }, [lineIdx, charIdx, onDone]);

  // Any key / tap skips the boot sequence immediately
  useEffect(() => {
    const skip = () => {
      if (rafRef.current) clearTimeout(rafRef.current);
      setFadeOut(true);
      setTimeout(() => { setDone(true); onDone(); }, 650);
    };
    window.addEventListener('keydown', skip);
    window.addEventListener('pointerdown', skip);
    return () => {
      window.removeEventListener('keydown', skip);
      window.removeEventListener('pointerdown', skip);
    };
  }, [onDone]);

  if (done) return null;
  return (
    <div
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center"
      style={{ background: 'var(--t-bg)', opacity: fadeOut ? 0 : 1, transition: 'opacity 0.6s ease' }}
    >
      {/* Ambient glow behind terminal */}
      <div className="absolute inset-0 pointer-events-none" style={{
        background: 'radial-gradient(ellipse 60% 50% at 50% 50%, rgba(0,229,255,0.04) 0%, transparent 70%)',
      }} />

      {/* Terminal window */}
      <div className="relative w-full max-w-2xl mx-auto">
        {/* Window chrome */}
        <div className="flex items-center gap-2 px-4 py-2" style={{ background: '#111', border: '1px solid rgba(0,229,255,0.15)', borderBottom: 'none' }}>
          <span className="w-2.5 h-2.5" style={{ background: RED   }} />
          <span className="w-2.5 h-2.5" style={{ background: AMBER }} />
          <span className="w-2.5 h-2.5" style={{ background: GREEN }} />
          <span className="text-[10px] font-mono ml-2" style={{ color: '#444' }}>aero-terminal — bash</span>
        </div>

        {/* Output area */}
        <div
          ref={termRef}
          className="px-5 py-4 overflow-hidden"
          style={{ background: '#080808', border: '1px solid rgba(0,229,255,0.15)', minHeight: 340, maxHeight: 420 }}
        >
          {/* Committed lines */}
          {visibleLines.map((line, i) => (
            <div key={i} className="text-xs leading-6 font-mono" style={{ color: line.color ?? '#888' }}>
              {line.text}
            </div>
          ))}

          {/* Currently-typing line */}
          {lineIdx < BOOT_LINES.length && (
            <div className="text-xs leading-6 font-mono flex items-center gap-0"
              style={{ color: BOOT_LINES[lineIdx]?.color ?? '#888' }}>
              {currentText}
              <span className="cursor-blink ml-px" style={{ color: CYAN }}>█</span>
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div style={{ background: '#0d0d0d', border: '1px solid rgba(0,229,255,0.12)', borderTop: 'none', padding: '6px 20px' }}>
          <div className="w-full h-px" style={{ background: '#1a1a1a' }}>
            <div className="h-px transition-all duration-300"
              style={{
                width: `${Math.round((lineIdx / BOOT_LINES.length) * 100)}%`,
                background: CYAN,
                boxShadow: `0 0 8px ${CYAN}`,
              }} />
          </div>
        </div>
      </div>

      {/* Skip hint */}
      <div className="absolute bottom-6 right-8 text-[10px] font-mono" style={{ color: '#333' }}>
        PRESS ANY KEY TO SKIP
      </div>
    </div>
  );
}
