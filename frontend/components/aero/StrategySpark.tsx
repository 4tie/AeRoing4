"use client";
import { useEffect, useRef, useState } from "react";

// Deterministic pseudo-random equity curve seeded by strategy name
function seededCurve(name: string, points = 20): number[] {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (Math.imul(31, h) + name.charCodeAt(i)) | 0;
  const rng = () => { h = (Math.imul(1664525, h) + 1013904223) | 0; return (h >>> 0) / 0xffffffff; };
  const vals: number[] = [0];
  for (let i = 1; i < points; i++) vals.push(vals[i - 1] + (rng() - 0.44) * 2);
  return vals;
}

interface Props { name: string; selected: boolean; width?: number; height?: number }

export function StrategySpark({ name, selected, width = 48, height = 22 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [animT, setAnimT] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  const curve = seededCurve(name);
  const minV = Math.min(...curve);
  const maxV = Math.max(...curve);
  const range = maxV - minV || 1;
  const isPositive = curve[curve.length - 1] >= curve[0];
  const color = selected ? "#00E5FF" : isPositive ? "#00FF88" : "#FF3B5C";
  const dim = selected ? 1 : 0.55;

  // Animate draw-on when first mounted
  useEffect(() => {
    startRef.current = null;
    setAnimT(0);
    const DURATION = 600;
    const go = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const t = Math.min((now - startRef.current) / DURATION, 1);
      setAnimT(t);
      if (t < 1) rafRef.current = requestAnimationFrame(go);
    };
    rafRef.current = requestAnimationFrame(go);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const pad = 2;
    const W = width - pad * 2;
    const H = height - pad * 2;

    // Number of points to draw based on animT
    const visibleCount = Math.max(2, Math.round(animT * curve.length));
    const pts = curve.slice(0, visibleCount);

    const px = (i: number) => pad + (i / (curve.length - 1)) * W;
    const py = (v: number) => pad + H - ((v - minV) / range) * H;

    // Gradient fill
    const grad = ctx.createLinearGradient(0, pad, 0, pad + H);
    grad.addColorStop(0, `${color}44`);
    grad.addColorStop(1, `${color}00`);

    ctx.beginPath();
    pts.forEach((v, i) => {
      const x = px(i); const y = py(v);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    // Close fill down to baseline
    ctx.lineTo(px(pts.length - 1), pad + H);
    ctx.lineTo(px(0), pad + H);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.globalAlpha = dim;
    ctx.fill();

    // Line stroke
    ctx.beginPath();
    pts.forEach((v, i) => {
      const x = px(i); const y = py(v);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    ctx.globalAlpha = dim;
    ctx.stroke();

    // Endpoint dot
    if (animT >= 1) {
      const lx = px(pts.length - 1);
      const ly = py(pts[pts.length - 1]);
      ctx.beginPath();
      ctx.arc(lx, ly, 2, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = 1;
      ctx.fill();
    }
  }, [animT, color, dim, curve, minV, range, width, height]);

  return <canvas ref={canvasRef} style={{ width, height, display: "block" }} />;
}
