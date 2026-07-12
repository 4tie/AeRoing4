'use client';
import { useEffect, useState, useRef } from 'react';

// Scenarios × Metrics grid
const SCENARIOS = ['Bear 2022', "Flash Jun'23", 'Bull 2021', 'Flat 2023', "Crash Mar'20"];
const METRICS   = ['Profit %', 'Drawdown', 'Win Rate', 'Sharpe', 'Recovery'];

// Empty data - will be populated from backend when available
const TARGET: number[][] = [
  [0, 0, 0, 0, 0],
  [0, 0, 0, 0, 0],
  [0, 0, 0, 0, 0],
  [0, 0, 0, 0, 0],
  [0, 0, 0, 0, 0],
];

function lerp(a: number, b: number, t: number) { return a + (b - a) * t; }

function cellColor(val: number, animated: number): string {
  const v = val * animated;
  const intensity = Math.min(Math.abs(v) / 50, 1);
  if (v >= 0) return `rgba(0,255,136,${lerp(0.04, 0.28, intensity)})`;
  else        return `rgba(255,59,92,${lerp(0.04, 0.32, intensity)})`;
}

function textColor(val: number) {
  return val >= 0 ? '#00FF88' : '#FF3B5C';
}

export function StressTestHeatmap({ active, data }: { active: boolean; data?: number[][] }) {
  // Use provided data or empty placeholder
  const heatmapData = data || TARGET;
  
  // animatedT[row][col] goes from 0 → 1 with staggered delays
  const [animT, setAnimT] = useState<number[][]>(
    () => heatmapData.map((row) => row.map(() => 0))
  );
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  const TOTAL_MS = 1800; // total animation window
  const STAGGER = 90;    // ms between each cell reveal

  useEffect(() => {
    if (!active) {
      setAnimT(heatmapData.map((row) => row.map(() => 0)));
      startRef.current = null;
      return;
    }

    const animate = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const elapsed = now - startRef.current;

      setAnimT(
        heatmapData.map((row, ri) =>
          row.map((_, ci) => {
            const cellStart = (ri * METRICS.length + ci) * STAGGER;
            const cellElapsed = elapsed - cellStart;
            if (cellElapsed <= 0) return 0;
            return Math.min(cellElapsed / 400, 1); // each cell takes 400ms to fill
          })
        )
      );

      if (elapsed < TOTAL_MS + METRICS.length * STAGGER + 400) {
        rafRef.current = requestAnimationFrame(animate);
      }
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [active, heatmapData]);

  const hasData = heatmapData.some(row => row.some(val => val !== 0));

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <span className="t-label">STRESS TEST MATRIX</span>
        {active && (
          <span className="text-[10px] font-mono animate-pulse flex items-center gap-1" style={{ color: 'var(--t-cyan)' }}>
            <span className="w-1.5 h-1.5 inline-block" style={{ background: 'var(--t-cyan)' }} />
            RUNNING
          </span>
        )}
      </div>

      {!hasData ? (
        <div className="text-xs font-mono py-8 text-center" style={{ color: 'var(--t-muted)' }}>
          No stress test data available. Run a stress test to populate this matrix.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse font-mono">
              <thead>
                <tr>
                  <th className="text-left pr-3 pb-2 font-medium w-28" style={{ color: 'rgba(255,255,255,0.15)' }}>Scenario</th>
                  {METRICS.map((m) => (
                    <th key={m} className="pb-2 text-center font-medium px-1 min-w-[72px]" style={{ color: 'var(--t-muted)' }}>{m}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmapData.map((row, ri) => (
                  <tr key={ri}>
                    <td className="pr-3 py-1 font-mono whitespace-nowrap" style={{ color: 'var(--t-muted)' }}>{SCENARIOS[ri]}</td>
                    {row.map((val, ci) => {
                      const t = animT[ri]?.[ci] ?? 0;
                      const displayed = val * t;
                      return (
                        <td key={ci} className="px-1 py-1">
                          <div
                            className="rounded-md px-1.5 py-1.5 text-center font-mono font-semibold transition-all duration-75 min-w-[64px]"
                            style={{
                              background: cellColor(val, t),
                              color: t > 0.1 ? textColor(val) : '#334155',
                              transform: `scale(${0.92 + t * 0.08})`,
                              opacity: 0.3 + t * 0.7,
                            }}
                          >
                            {t > 0.05
                              ? `${val >= 0 ? '+' : ''}${displayed.toFixed(1)}${METRICS[ci].includes('%') || ci === 0 || ci === 4 ? '%' : ci === 1 ? '%' : ''}`
                              : '···'}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 pt-1">
            {[['rgba(0,255,136,0.4)','Positive'],['rgba(255,59,92,0.4)','Negative'],['rgba(255,59,92,0.7)','Critical (<-15%)']].map(([bg, label]) => (
              <div key={label} className="flex items-center gap-1.5 text-[10px] font-mono" style={{ color: 'var(--t-muted)' }}>
                <span className="w-2.5 h-2.5 inline-block" style={{ background: bg }} />
                {label}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
