"use client";
import { useState, useRef, useEffect } from "react";
import { useAeroStore } from "@/lib/aeroStore";
import { uploadStrategy } from "@/lib/api";
import { UploadCloud, Check, FileCode, Loader2 } from "lucide-react";

const API_BASE_URL = "";

const FIXES = [
  { id: 1, sev: "HIGH",   title: "TIGHTEN STOPLOSS",     desc: "Reduce stoploss from -10% to -7%",              diff: '-    stoploss = -0.10\n+    stoploss = -0.07' },
  { id: 2, sev: "MEDIUM", title: "ADD TREND FILTER",     desc: "Add BTC dominance HTF trend gate on entry",     diff: "+        (dataframe['btc_1h_trend'] == 1) &" },
  { id: 3, sev: "MEDIUM", title: "REDUCE POSITION SIZE", desc: "Cap position to 25% stake, max 4 open trades",  diff: '+    stake_amount = "unlimited"\n+    max_open_trades = 4' },
];

const Panel = ({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) => (
  <div className={`t-card ${className}`}>
    <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: "1px solid var(--t-border)" }}>
      <span className="w-1.5 h-1.5 shrink-0" style={{ background: "var(--t-cyan)" }} />
      <span className="t-label">{label}</span>
    </div>
    <div className="p-3">{children}</div>
  </div>
);

export function TabFix() {
  const { selectedStrategyName } = useAeroStore();
  const [code, setCode] = useState("");
  const [codeLoading, setCodeLoading] = useState(false);
  const [applied, setApplied] = useState<number[]>([]);
  const [showDiff, setShowDiff] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedName, setUploadedName] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Load strategy source from backend when strategy changes
  useEffect(() => {
    if (!selectedStrategyName) return;
    setCodeLoading(true);
    fetch(`${API_BASE_URL}/api/strategies/content?filename=${encodeURIComponent(selectedStrategyName)}.py`)
      .then((r) => r.ok ? r.json() : null)
      .then((data: Record<string, unknown> | null) => {
        const src = String(data?.content ?? data?.file_content ?? "");
        setCode(src || `# Could not load ${selectedStrategyName}.py from backend`);
      })
      .catch(() => setCode(`# Could not load ${selectedStrategyName}.py`))
      .finally(() => setCodeLoading(false));
  }, [selectedStrategyName]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return;
    setUploading(true);
    const r = await uploadStrategy(f);
    setUploadedName(r.name); setUploading(false);
    // Reload code after upload
    if (r.ok) {
      const res = await fetch(`${API_BASE_URL}/api/strategies/content?filename=${encodeURIComponent(r.name)}.py`);
      if (res.ok) {
        const d = await res.json() as Record<string, unknown>;
        setCode(String(d.content ?? d.file_content ?? ""));
      }
    }
  };

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 03 · FIX</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: "var(--t-text)", letterSpacing: "-0.02em" }}>Fix</h1>
        <span className="text-xs font-mono" style={{ color: "var(--t-muted)" }}>Apply AI-suggested improvements to your strategy</span>
      </div>

      {/* File selector */}
      <Panel label="STRATEGY SOURCE">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono"
            style={{ background: "rgba(0,229,255,0.06)", border: "1px solid var(--t-border-hi)", color: "var(--t-cyan)" }}>
            <FileCode size={12} />
            {uploadedName ?? selectedStrategyName}.py
          </div>
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono transition-all"
            style={{ border: "1px solid var(--t-border)", color: "var(--t-label)", background: "transparent" }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--t-cyan)")}
            onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--t-border)")}>
            {uploading ? <span className="cursor-blink" style={{ color: "var(--t-cyan)" }}>█</span> : <UploadCloud size={12} />}
            CHOOSE FILE
          </button>
          <input ref={fileRef} type="file" accept=".py" className="hidden" onChange={handleUpload} />
        </div>
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Code editor */}
        <div className="t-card overflow-hidden">
          <div className="px-3 py-1.5 flex items-center justify-between" style={{ borderBottom: "1px solid var(--t-border)", background: "rgba(0,229,255,0.03)" }}>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2" style={{ background: "var(--t-red)" }} />
              <span className="w-2 h-2" style={{ background: "var(--t-yellow)" }} />
              <span className="w-2 h-2" style={{ background: "var(--t-green)" }} />
            </div>
            <span className="t-label">STRATEGY SOURCE · {String(code.split("\n").length)} lines</span>
          </div>
          <textarea className="w-full h-[380px] p-4 text-xs font-mono resize-none outline-none t-focus"
            style={{ background: "#080808", color: "var(--t-text)", border: "none", lineHeight: "1.7" }}
            value={code} onChange={e => setCode(e.target.value)} spellCheck={false} />
        </div>

        {/* Fix suggestions */}
        <div className="space-y-3">
          <span className="t-label block">AI FIX SUGGESTIONS</span>
          {FIXES.map((fix) => (
            <div key={fix.id} className="t-card overflow-hidden transition-all"
              style={{ borderColor: applied.includes(fix.id) ? "rgba(0,255,136,0.25)" : "var(--t-border)" }}>
              <div className="p-3">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <div>
                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 mr-2"
                      style={{ background: fix.sev === "HIGH" ? "rgba(255,59,92,0.12)" : "rgba(255,184,0,0.1)", color: fix.sev === "HIGH" ? "var(--t-red)" : "var(--t-yellow)", border: `1px solid ${fix.sev === "HIGH" ? "rgba(255,59,92,0.3)" : "rgba(255,184,0,0.25)"}` }}>
                      {fix.sev}
                    </span>
                    <span className="text-xs font-mono font-bold" style={{ color: "var(--t-cyan)" }}>{fix.title}</span>
                  </div>
                  {applied.includes(fix.id) ? (
                    <span className="text-xs font-mono flex items-center gap-1" style={{ color: "var(--t-green)" }}><Check size={10} /> APPLIED</span>
                  ) : (
                    <div className="flex gap-2 shrink-0">
                      <button onClick={() => setShowDiff(showDiff === fix.id ? null : fix.id)}
                        className="text-xs font-mono px-2 py-1 transition-all"
                        style={{ border: "1px solid var(--t-border)", color: "var(--t-label)", background: "transparent" }}
                        onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--t-border-hi)")}
                        onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--t-border)")}>DIFF</button>
                      <button onClick={() => { setApplied(p => [...p, fix.id]); setShowDiff(null); }}
                        className="text-xs font-mono px-2 py-1 transition-all"
                        style={{ border: "1px solid var(--t-border-hi)", color: "var(--t-cyan)", background: "rgba(0,229,255,0.06)" }}
                        onMouseEnter={e => (e.currentTarget.style.background = "rgba(0,229,255,0.12)")}
                        onMouseLeave={e => (e.currentTarget.style.background = "rgba(0,229,255,0.06)")}>APPLY FIX</button>
                    </div>
                  )}
                </div>
                <p className="text-xs font-mono" style={{ color: "var(--t-muted)" }}>{fix.desc}</p>
              </div>
              {showDiff === fix.id && (
                <div className="p-3" style={{ borderTop: "1px solid var(--t-border)", background: "#080808" }}>
                  <span className="t-label block mb-2">--- before / +++ after</span>
                  <pre className="text-xs font-mono leading-relaxed">
                    {fix.diff.split("\n").map((line, i) => (
                      <div key={i} style={{ color: line.startsWith("+") ? "var(--t-green)" : line.startsWith("-") ? "var(--t-red)" : "var(--t-muted)" }}>{line}</div>
                    ))}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
