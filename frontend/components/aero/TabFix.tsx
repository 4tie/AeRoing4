'use client';
import { useState, useRef, useEffect } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { uploadStrategy } from '@/lib/api';
import { UploadCloud, FileCode, Loader2 } from 'lucide-react';

const API_BASE_URL = '';

const Panel = ({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) => (
  <div className={`t-card ${className}`}>
    <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
      <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
      <span className="t-label">{label}</span>
    </div>
    <div className="p-3">{children}</div>
  </div>
);

export function TabFix() {
  const { selectedStrategyName } = useAeroStore();
  const [code, setCode] = useState('');
  const [codeLoading, setCodeLoading] = useState(false);
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
        const src = String(data?.content ?? data?.file_content ?? '');
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
        setCode(String(d.content ?? d.file_content ?? ''));
      }
    }
  };

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 03 · FIX</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>Fix</h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Apply AI-suggested improvements to your strategy</span>
      </div>

      {/* File selector */}
      <Panel label="STRATEGY SOURCE">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono"
            style={{ background: 'rgba(0,229,255,0.06)', border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)' }}>
            <FileCode size={12} />
            {uploadedName ?? selectedStrategyName}.py
          </div>
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono transition-all"
            style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-cyan)')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
            {uploading ? <span className="cursor-blink" style={{ color: 'var(--t-cyan)' }}>█</span> : <UploadCloud size={12} />}
            CHOOSE FILE
          </button>
          <input ref={fileRef} type="file" accept=".py" className="hidden" onChange={handleUpload} />
        </div>
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Code editor */}
        <div className="t-card overflow-hidden">
          <div className="px-3 py-1.5 flex items-center justify-between" style={{ borderBottom: '1px solid var(--t-border)', background: 'rgba(0,229,255,0.03)' }}>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2" style={{ background: 'var(--t-red)' }} />
              <span className="w-2 h-2" style={{ background: 'var(--t-yellow)' }} />
              <span className="w-2 h-2" style={{ background: 'var(--t-green)' }} />
            </div>
            <span className="t-label">STRATEGY SOURCE · {String(code.split('\n').length)} lines</span>
          </div>
          <textarea className="w-full h-[380px] p-4 text-xs font-mono resize-none outline-none t-focus"
            style={{ background: '#080808', color: 'var(--t-text)', border: 'none', lineHeight: '1.7' }}
            value={code} onChange={e => setCode(e.target.value)} spellCheck={false} />
        </div>

        {/* Fix suggestions placeholder */}
        <div className="space-y-3">
          <span className="t-label block">AI FIX SUGGESTIONS</span>
          <div className="text-xs font-mono py-12 text-center" style={{ color: 'var(--t-muted)' }}>
            No fix suggestions available. AI analysis will provide suggestions here when available.
          </div>
        </div>
      </div>
    </div>
  );
}
