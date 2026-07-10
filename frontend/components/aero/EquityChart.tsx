"use client";
import { useEffect, useRef, useState, useCallback } from "react";

interface Point { time: string; value: number }
interface Props  { data: Point[] }

const CYAN  = "#00E5FF";
const PAD   = { top: 12, right: 8, bottom: 28, left: 42 };
const DURATION_MS = 1400; // line draw duration

function easeInOut(t: number) {
  return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
}

export function EquityChart({ data }: Props) {
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const wrapRef    = useRef<HTMLDivElement>(null);
  const rafRef     = useRef<number | null>(null);
  const startRef   = useRef<number | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; point: Point } | null>(null);

  // Resolve canvas logical dimensions from wrapper
  const getDims = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return { w: 600, h: 200 };
    return { w: el.clientWidth, h: el.clientHeight };
  }, []);

  const draw = useCallback((progress: number) => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const { w, h } = getDims();
    canvas.width  = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width  = `${w}px`;
    canvas.style.height = `${h}px`;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const innerW = w - PAD.left - PAD.right;
    const innerH = h - PAD.top  - PAD.bottom;
    const vals   = data.map(d => d.value);
    const minV   = Math.min(...vals);
    const maxV   = Math.max(...vals);
    const range  = maxV - minV || 1;

    const px = (i: number) => PAD.left + (i / (data.length - 1)) * innerW;
    const py = (v: number) => PAD.top  + innerH - ((v - minV) / range) * innerH;

    // ── Grid lines ────────────────────────────────────────────
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth   = 1;
    for (let g = 0; g <= 4; g++) {
      const y = PAD.top + (g / 4) * innerH;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + innerW, y); ctx.stroke();
    }

    // ── Y-axis labels ─────────────────────────────────────────
    ctx.fillStyle  = "#444";
    ctx.font       = `10px monospace`;
    ctx.textAlign  = "right";
    for (let g = 0; g <= 4; g++) {
      const v = minV + ((4 - g) / 4) * range;
      const y = PAD.top + (g / 4) * innerH;
      ctx.fillText(`$${Math.round(v)}`, PAD.left - 4, y + 3);
    }

    // ── X-axis labels (sparse) ────────────────────────────────
    ctx.textAlign  = "center";
    ctx.fillStyle  = "#444";
    const step = Math.floor(data.length / 5);
    for (let i = 0; i < data.length; i += step) {
      ctx.fillText(data[i].time, px(i), h - 6);
    }

    // ── How many segments to draw (animated) ─────────────────
    const visiblePts = Math.max(2, Math.round(progress * (data.length - 1)) + 1);
    const pts = data.slice(0, visiblePts);

    // ── Filled area (clip to drawn path + baseline) ───────────
    const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + innerH);
    grad.addColorStop(0,   "rgba(0,229,255,0.22)");
    grad.addColorStop(0.6, "rgba(0,229,255,0.06)");
    grad.addColorStop(1,   "rgba(0,229,255,0)");

    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = px(i), y = py(p.value);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(px(pts.length - 1), PAD.top + innerH);
    ctx.lineTo(px(0),              PAD.top + innerH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // ── Main line ─────────────────────────────────────────────
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = px(i), y = py(p.value);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = CYAN;
    ctx.lineWidth   = 1.8;
    ctx.lineJoin    = "round";
    ctx.shadowColor = "rgba(0,229,255,0.55)";
    ctx.shadowBlur  = 6;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // ── Moving tip dot ────────────────────────────────────────
    if (pts.length >= 2) {
      const tip = pts[pts.length - 1];
      const tx  = px(pts.length - 1);
      const ty  = py(tip.value);

      // outer ring
      ctx.beginPath();
      ctx.arc(tx, ty, 5, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(0,229,255,0.18)";
      ctx.fill();

      // inner dot
      ctx.beginPath();
      ctx.arc(tx, ty, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = CYAN;
      ctx.shadowColor = "rgba(0,229,255,0.9)";
      ctx.shadowBlur  = 8;
      ctx.fill();
      ctx.shadowBlur  = 0;
    }
  }, [data, getDims]);

  // Kick off animation whenever data changes
  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    startRef.current = null;

    const animate = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const raw = Math.min((now - startRef.current) / DURATION_MS, 1);
      draw(easeInOut(raw));
      if (raw < 1) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [data, draw]);

  // Redraw on resize
  useEffect(() => {
    const ro = new ResizeObserver(() => draw(1));
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [draw]);

  // Tooltip on mouse move
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;
    const rect   = canvas.getBoundingClientRect();
    const mx     = e.clientX - rect.left;
    const innerW = rect.width - PAD.left - PAD.right;
    const idx    = Math.round(((mx - PAD.left) / innerW) * (data.length - 1));
    const clamped = Math.max(0, Math.min(data.length - 1, idx));
    const vals   = data.map(d => d.value);
    const minV   = Math.min(...vals);
    const maxV   = Math.max(...vals);
    const range  = maxV - minV || 1;
    const innerH = rect.height - PAD.top - PAD.bottom;
    const x      = PAD.left + (clamped / (data.length - 1)) * innerW;
    const y      = PAD.top  + innerH - ((data[clamped].value - minV) / range) * innerH;
    setTooltip({ x, y, point: data[clamped] });
  }, [data]);

  return (
    <div ref={wrapRef} className="relative w-full" style={{ height: 210 }}>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTooltip(null)}
      />
      {tooltip && (
        <div className="pointer-events-none absolute z-10 px-2 py-1.5 text-[11px] font-mono"
          style={{
            left: tooltip.x + 10,
            top:  Math.max(4, tooltip.y - 36),
            background: "#0d0d0d",
            border: "1px solid rgba(0,229,255,0.35)",
            color: CYAN,
            whiteSpace: "nowrap",
          }}>
          <div style={{ color: "#555" }}>{tooltip.point.time}</div>
          <div style={{ color: CYAN }}>${tooltip.point.value}</div>
        </div>
      )}
    </div>
  );
}
