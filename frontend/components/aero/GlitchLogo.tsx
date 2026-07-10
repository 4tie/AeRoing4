"use client";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";

// Filled in below
export function GlitchLogo() {
  const [glitch, setGlitch] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Randomly fire a glitch every 3–8 seconds
    const schedule = () => {
      const wait = 3000 + Math.random() * 5000;
      timerRef.current = setTimeout(() => {
        setGlitch(true);
        // Hold glitch state for one animation cycle (450ms), then reset
        timerRef.current = setTimeout(() => {
          setGlitch(false);
          schedule(); // queue next glitch
        }, 460);
      }, wait);
    };
    // Small initial delay so it doesn't fire instantly on mount
    timerRef.current = setTimeout(schedule, 1200);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  return (
    <div className="flex items-center gap-2 pr-4 shrink-0" style={{ borderRight: "1px solid var(--t-border)" }}>
      <div className="glitch-icon-wrap" data-glitch={glitch ? "1" : "0"}>
        <Image src="/logo.png" alt="AeRo" width={16} height={16} className="object-contain" priority />
      </div>
      <span className="glitch-text" data-text="AeRo" data-glitch={glitch ? "1" : "0"}>
        Ae<span>Ro</span>
      </span>
    </div>
  );
}
