'use client';
import { useEffect, useRef } from 'react';
import type { DiscoveryPairResult } from '@/lib/api';

interface Props { pairs: DiscoveryPairResult[] }

export function ScoreDistributionChart({ pairs }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef   = useRef<HTMLDivElement>(null);
  const rafRef    = useRef<number | null>(null);
  const startRef  = useRef<number | null>(null);

  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    startRef.current = null;

    const DURATION = 900;
    const PAD = { top: 28, right: 8, bottom: 36, left: 32 };

    // Sort: valid candidates by score desc, then rejected (score = 0 for display)
    const valid   = pairs.filter(p => p.status === 'VALID_CANDIDATE' && p.rank_score !== null)
                         .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0));
    const invalid = pairs.filter(p => p.status !== 'VALID_CANDIDATE');
    const all     = [...valid, ...invalid];

    function barColor(p: DiscoveryPairResult): { fill: string; glow: string } {
      if (p.status === 'VALID_CANDIDATE') {
        const s = p.rank_score ?? 0;
        if (s >= 60) return { fill: '#00FF88', glow: 'rgba(0,255,136,0.4)' };
        if (s >= 35) return { fill: '#FFB800', glow: 'rgba(255,184,0,0.4)' };
        return { fill: '#00E5FF', glow: 'rgba(0,229,255,0.4)' };
      }
      if (p.status === 'EXECUTION_FAILURE' || p.status === 'ZERO_TRADES') return { fill: '#FF3B5C', glow: 'rgba(255,59,92,0.3)' };
      if (p.status === 'INSUFFICIENT_TRADES') return { fill: '#FFB800', glow: 'rgba(255,184,0,0.3)' };
      return { fill: '#333333', glow: 'transparent' };
    }

    const draw = (progress: number) => {
      const canvas = canvasRef.current;
      const wrap   = wrapRef.current;
      if (!canvas || !wrap) return;
      const dpr = window.devicePixelRatio || 1;
      const W   = wrap.clientWidth;
      const H   = wrap.clientHeight;
      canvas.width  = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width  = `${W}px`;
      canvas.style.height = `${H}px`;
      const ctx = canvas.getContext('2d')!;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, W, H);

      const innerW = W - PAD.left - PAD.right;
      const innerH = H - PAD.top  - PAD.bottom;
      const n      = all.length;
      if (n === 0) return;

      const barW   = Math.max(2, Math.floor((innerW / n) * 0.72));
      const gap    = Math.floor((innerW - barW * n) / (n + 1));

      // Grid lines at 0, 25, 50, 75, 100
      ctx.font      = `${10 * Math.min(dpr, 1.5)}px monospace`;
      ctx.textAlign = 'right';
      for (let g = 0; g <= 4; g++) {
        const val = g * 25;
        const y   = PAD.top + innerH - (val / 100) * innerH;
        ctx.strokeStyle = 'rgba(255,255,255,0.05)';
        ctx.lineWidth   = 1;
        ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + innerW, y); ctx.stroke();
        ctx.fillStyle = '#444';
        ctx.fillText(String(val), PAD.left - 4, y + 3);
      }

      // Score = 100 reference line
      const refY = PAD.top;
      ctx.strokeStyle = 'rgba(0,229,255,0.12)';
      ctx.setLineDash([3, 5]);
      ctx.beginPath(); ctx.moveTo(PAD.left, refY); ctx.lineTo(PAD.left + innerW, refY); ctx.stroke();
      ctx.setLineDash([]);

      // Bars
      all.forEach((pair, i) => {
        const score     = pair.rank_score ?? 0;
        const maxH      = (score / 100) * innerH * progress;
        const x         = PAD.left + gap + i * (barW + gap);
        const y         = PAD.top + innerH - maxH;
        const { fill, glow } = barColor(pair);

        if (maxH > 0.5) {
          // Glow shadow
          ctx.shadowColor = glow;
          ctx.shadowBlur  = score > 0 ? 6 : 0;
          ctx.fillStyle   = fill;
          ctx.fillRect(x, y, barW, maxH);
          ctx.shadowBlur  = 0;

          // Top cap line
          ctx.fillStyle = 'rgba(255,255,255,0.25)';
          ctx.fillRect(x, y, barW, 1);
        } else if (pair.status !== 'VALID_CANDIDATE') {
          // Zero-height placeholder for rejected pairs
          ctx.fillStyle = fill;
          ctx.globalAlpha = 0.25;
          ctx.fillRect(x, PAD.top + innerH - 2, barW, 2);
          ctx.globalAlpha = 1;
        }

        // Pair label (only when bars have settled enough)
        if (progress > 0.6) {
          const alpha  = Math.min(1, (progress - 0.6) / 0.4);
          const short  = pair.pair.replace('/USDT', '');
          ctx.globalAlpha = alpha;
          ctx.font      = '9px monospace';
          ctx.textAlign = 'center';
          ctx.fillStyle = pair.status === 'VALID_CANDIDATE' ? fill : '#444';
          ctx.save();
          ctx.translate(x + barW / 2, PAD.top + innerH + 14);
          ctx.rotate(-Math.PI / 4);
          ctx.fillText(short, 0, 0);
          ctx.restore();
          ctx.globalAlpha = 1;
        }

        // Rank badge on top 3
        if (pair.rank !== null && pair.rank <= 3 && progress > 0.85) {
          const alpha = Math.min(1, (progress - 0.85) / 0.15);
          ctx.globalAlpha = alpha;
          ctx.font      = 'bold 9px monospace';
          ctx.textAlign = 'center';
          ctx.fillStyle = '#00E5FF';
          ctx.fillText(`#${pair.rank}`, x + barW / 2, y - 4);
          ctx.globalAlpha = 1;
        }
      });

      // "SCORE DISTRIBUTION" label
      if (progress > 0.3) {
        ctx.globalAlpha = Math.min(1, (progress - 0.3) / 0.4);
        ctx.font      = '9px monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle = '#444';
        ctx.fillText(`${valid.length} valid  ·  ${invalid.length} rejected  ·  ${n} total`, PAD.left, 12);
        ctx.globalAlpha = 1;
      }
    };

    const animate = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const t = Math.min((now - startRef.current) / DURATION, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      draw(eased);
      if (t < 1) rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [pairs]);

  // Replay on resize
  useEffect(() => {
    const ro = new ResizeObserver(() => {
      startRef.current = null;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      const canvas = canvasRef.current;
      if (!canvas) return;
      // Redraw at full progress
      startRef.current = performance.now() - 1000;
    });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrapRef} style={{ width: '100%', height: 160, position: 'relative' }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
    </div>
  );
}
