'use client';
import { useEffect, useRef } from 'react';

interface Props { score: number; width?: number; height?: number }

export function RankScoreMeter({ score, width = 80, height = 8 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const startRef  = useRef<number | null>(null);
  const rafRef    = useRef<number | null>(null);

  useEffect(() => {
    startRef.current = null;
    const DURATION = 700;
    const color = score >= 60 ? '#00FF88' : score >= 35 ? '#FFB800' : '#FF3B5C';
    const glow  = score >= 60 ? 'rgba(0,255,136,0.5)' : score >= 35 ? 'rgba(255,184,0,0.5)' : 'rgba(255,59,92,0.5)';

    const draw = (progress: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width  = width  * dpr;
      canvas.height = height * dpr;
      canvas.style.width  = `${width}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext('2d')!;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);
      // Track
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(0, 0, width, height);
      // Fill
      const filled = (score / 100) * progress * width;
      if (filled > 0) {
        ctx.fillStyle = color;
        ctx.shadowColor = glow;
        ctx.shadowBlur  = 4;
        ctx.fillRect(0, 0, filled, height);
        ctx.shadowBlur  = 0;
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
  }, [score, width, height]);

  return <canvas ref={canvasRef} style={{ width, height, display: 'block' }} />;
}
