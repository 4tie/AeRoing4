'use client';
import { useEffect, useRef, useState } from 'react';
import { useAeroStore } from '@/lib/aeroStore';
import { getBackendSettings, saveBackendSettings, checkBackendHealth, BackendSettings, BackendHealth } from '@/lib/api';
import { Sun, Moon, RotateCcw, Check, AlertCircle, Loader2, Activity, RefreshCw } from 'lucide-react';

const Panel = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="t-card">
    <div className="px-3 py-1.5 flex items-center gap-2" style={{ borderBottom: '1px solid var(--t-border)' }}>
      <span className="w-1.5 h-1.5 shrink-0" style={{ background: 'var(--t-cyan)' }} />
      <span className="t-label">{label}</span>
    </div>
    <div className="p-4 space-y-4">{children}</div>
  </div>
);

const Field = ({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) => (
  <div>
    <span className="t-label block mb-1.5">{label}</span>
    {children}
    {hint && <span className="text-[10px] font-mono mt-1 block" style={{ color: 'var(--t-muted)' }}>{hint}</span>}
  </div>
);

const TInput = ({ value, onChange, type = 'text', placeholder = '' }: { value: string; onChange: (v: string) => void; type?: string; placeholder?: string }) => (
  <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
    className="w-full px-3 py-2 text-xs font-mono t-focus"
    style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} />
);

const TNumber = ({ value, onChange, min, max, step }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }) => (
  <input type="number" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))}
    className="w-full px-3 py-2 text-xs font-mono t-focus"
    style={{ background: 'var(--t-bg)', border: '1px solid var(--t-border)', color: 'var(--t-text)', outline: 'none' }} />
);

const TSwitch = ({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) => (
  <button onClick={() => onChange(!checked)}
    className="relative h-5 w-9 transition-all"
    style={{ border: '1px solid var(--t-border)', background: checked ? 'rgba(0,229,255,0.2)' : 'var(--t-bg)' }}>
    <span className="absolute top-0.5 h-3.5 w-3.5 transition-all"
      style={{ left: checked ? 'calc(100% - 18px)' : '3px', background: checked ? 'var(--t-cyan)' : 'var(--t-muted)' }} />
  </button>
);

/** Display a YYYYMMDD string as YYYY-MM-DD for readability */
const fmtDate = (d: string) => d.length === 8 ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}` : d;
/** Convert YYYY-MM-DD back to YYYYMMDD */
const unfmtDate = (d: string) => d.replace(/-/g, '');

// Exponential backoff delays (ms)
const RETRY_DELAYS = [2000, 4000, 8000];

export function TabSettings() {
  const store = useAeroStore();
  const { darkMode, toggleDarkMode, backendConnected, setBackendConnected, backendStatus, setBackendStatus,
    setBackendSettings, backendSettingsLoading, setBackendSettingsLoading,
    backendSettingsDirty, setBackendSettingsDirty } = store;

  const [settings, setSettings] = useState<BackendSettings | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [healthDetails, setHealthDetails] = useState<BackendHealth | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const patch = (partial: Partial<BackendSettings>) => {
    if (!settings) return;
    setSettings({ ...settings, ...partial });
    setBackendSettingsDirty(true);
  };

  /** Core fetch — no retry logic, just a single attempt */
  const fetchSettings = async (): Promise<BackendSettings | null> => {
    setBackendSettingsLoading(true);
    setError(null);
    const s = await getBackendSettings();
    setBackendSettingsLoading(false);
    if (s) {
      setSettings(s);
      setBackendSettings(s);
      setBackendSettingsDirty(false);
      store.setDefaultStrategyPath(s.strategies_directory_path);
      setRetrying(false);
      settingsLoadedRef.current = true;
    }
    return s;
  };

  /**
   * Load with exponential backoff: 3 attempts at 2 s / 4 s / 8 s.
   * Calling this explicitly (e.g. Retry button) resets the attempt counter.
   */
  const load = async (attempt = 0) => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    const s = await fetchSettings();
    if (!s) {
      if (attempt < RETRY_DELAYS.length) {
        const delay = RETRY_DELAYS[attempt];
        setRetrying(true);
        setError(
          `Backend unreachable. Retrying in ${delay / 1000}s… (attempt ${attempt + 1}/${RETRY_DELAYS.length})`
        );
        retryTimer.current = setTimeout(() => load(attempt + 1), delay);
      } else {
        setRetrying(false);
        setError('Could not reach backend after 3 attempts. Is the API server running?');
      }
    }
  };

  const save = async () => {
    if (!settings) return;
    setError(null);
    const res = await saveBackendSettings(settings);
    if (res.ok) {
      setSaved(true);
      setBackendSettingsDirty(false);
      setBackendSettings(settings);
      setTimeout(() => setSaved(false), 2000);
    } else {
      setError(res.error ?? 'Save failed');
    }
  };

  // Use refs to avoid stale closures inside interval callbacks
  const settingsLoadedRef = useRef(false);
  const prevConnectedRef  = useRef<boolean | null>(null);

  const checkHealth = async () => {
    const h = await checkBackendHealth();
    setHealthDetails(h);
    const reachable = h.reachable ?? h.ok;
    const wasOffline = prevConnectedRef.current === false;
    prevConnectedRef.current = reachable;
    setBackendConnected(reachable);
    setBackendStatus(reachable ? 'CONNECTED' : 'OFFLINE');
    // Trigger settings reload only on true offline→online transition with no loaded settings
    if (reachable && wasOffline && !settingsLoadedRef.current) {
      load(0);
    }
  };

  useEffect(() => {
    load(0);
    // Set initial prev-connected so the first health-OK doesn't look like a transition
    prevConnectedRef.current = null;
    const id = setInterval(checkHealth, 5000);
    // Run first health check after a short delay so prev-connected is initialised
    const first = setTimeout(() => checkHealth(), 500);
    return () => {
      clearInterval(id);
      clearTimeout(first);
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Loading / Error states ────────────────────────────────────────────────
  if (!settings) {
    return (
      <div className="space-y-4 max-w-2xl">
        <div className="mb-4">
          <span className="t-label block mb-1">TAB 05 · SETTINGS</span>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>Settings</h1>
          <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Configure backend &amp; AI services</span>
        </div>

        {retrying || backendSettingsLoading ? (
          <div className="p-5 t-card flex items-center gap-3">
            <Loader2 size={15} className="animate-spin shrink-0" style={{ color: 'var(--t-cyan)' }} />
            <div>
              <span className="text-xs font-mono block" style={{ color: 'var(--t-text)' }}>
                {retrying ? 'Connecting to backend…' : 'Loading settings…'}
              </span>
              {error && (
                <span className="text-[11px] font-mono block mt-0.5" style={{ color: 'var(--t-muted)' }}>{error}</span>
              )}
            </div>
          </div>
        ) : error ? (
          <div className="p-4 t-card" style={{ borderColor: 'rgba(255,59,92,0.35)' }}>
            <div className="flex items-start gap-3 mb-3">
              <AlertCircle size={14} style={{ color: 'var(--t-red)', flexShrink: 0, marginTop: 2 }} />
              <div>
                <span className="text-xs font-mono block font-bold" style={{ color: 'var(--t-red)' }}>BACKEND UNREACHABLE</span>
                <span className="text-xs font-mono block mt-1" style={{ color: 'var(--t-muted)' }}>{error}</span>
              </div>
            </div>
            <button onClick={() => load(0)}
              className="flex items-center gap-2 px-4 py-2 text-xs font-mono transition-all"
              style={{ border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)', background: 'rgba(0,229,255,0.06)' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,229,255,0.12)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'rgba(0,229,255,0.06)')}>
              <RefreshCw size={12} /> RETRY NOW
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const freqtradeCheck = healthDetails?.checks?.find(check => check.check === 'freqtrade_cli');
  const resolvedFreqtrade = freqtradeCheck?.resolved_executable ?? freqtradeCheck?.executable ?? null;
  const freqtradeAvailable = freqtradeCheck?.ok === true;

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="mb-4">
        <span className="t-label block mb-1">TAB 05 · SETTINGS</span>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--t-text)', letterSpacing: '-0.02em' }}>Settings</h1>
        <span className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>Backend configuration, paths, Ollama &amp; research pipeline</span>
      </div>

      {/* Connection banner */}
      <div className="t-card p-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2" style={{ background: backendConnected ? 'var(--t-green)' : 'var(--t-red)', boxShadow: backendConnected ? '0 0 8px var(--t-green)' : '0 0 8px var(--t-red)' }} />
            <span className="text-xs font-mono font-semibold" style={{ color: backendConnected ? 'var(--t-green)' : 'var(--t-red)' }}>{backendStatus}</span>
          </div>
          <span className="text-[10px] font-mono" style={{ color: 'var(--t-muted)' }}>Backend API</span>
        </div>
        <button onClick={checkHealth}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-mono transition-all"
          style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
          onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
          <Activity size={11} /> REFRESH
        </button>
      </div>

      {error && !retrying && (
        <div className="p-3 flex items-start gap-2" style={{ background: 'rgba(255,59,92,0.08)', border: '1px solid rgba(255,59,92,0.35)' }}>
          <AlertCircle size={14} style={{ color: 'var(--t-red)', flexShrink: 0, marginTop: 1 }} />
          <span className="text-xs font-mono flex-1" style={{ color: 'var(--t-red)' }}>{error}</span>
        </div>
      )}

      <Panel label="APPEARANCE">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs font-mono" style={{ color: 'var(--t-text)' }}>Theme</span>
            <span className="text-[11px] font-mono block" style={{ color: 'var(--t-muted)' }}>Toggle dark / light mode</span>
          </div>
          <button onClick={toggleDarkMode}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono transition-all"
            style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
            {darkMode ? <Moon size={12} /> : <Sun size={12} />}
            {darkMode ? 'DARK' : 'LIGHT'}
          </button>
        </div>
      </Panel>

      <Panel label="PATHS">
        <Field label="FREQTRADE EXECUTABLE" hint="Command used to invoke Freqtrade (e.g. py -m freqtrade).">
          <TInput value={settings.freqtrade_executable_path} onChange={v => patch({ freqtrade_executable_path: v })} />
          <div className="mt-2 p-2 text-[10px] font-mono space-y-1" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--t-border)' }}>
            <div style={{ color: 'var(--t-muted)' }}>
              Configured value: <span style={{ color: 'var(--t-text)' }}>{freqtradeCheck?.configured_executable ?? settings.freqtrade_executable_path}</span>
            </div>
            <div style={{ color: 'var(--t-muted)' }}>
              Resolved executable: <span style={{ color: 'var(--t-text)' }}>{resolvedFreqtrade ?? 'Run health check'}</span>
            </div>
            <div style={{ color: freqtradeCheck ? (freqtradeAvailable ? 'var(--t-green)' : 'var(--t-red)') : 'var(--t-muted)' }}>
              Freqtrade: {freqtradeCheck ? (freqtradeAvailable ? 'available' : 'unavailable') : 'not checked yet'}
            </div>
            {freqtradeCheck?.detail && (
              <div style={{ color: 'var(--t-muted)' }}>{freqtradeCheck.detail}</div>
            )}
          </div>
        </Field>
        <Field label="STRATEGIES DIRECTORY" hint="Directory where strategy .py files live.">
          <TInput value={settings.strategies_directory_path} onChange={v => patch({ strategies_directory_path: v })} />
        </Field>
        <Field label="USER DATA DIRECTORY" hint="Freqtrade user_data root.">
          <TInput value={settings.user_data_directory_path} onChange={v => patch({ user_data_directory_path: v })} />
        </Field>
        <Field label="DEFAULT CONFIG FILE" hint="Path to config.json used by backtests.">
          <TInput value={settings.default_config_file_path} onChange={v => patch({ default_config_file_path: v })} />
        </Field>
      </Panel>

      {/* ── Research Data Zones ───────────────────────────────────────── */}
      <Panel label="RESEARCH DATA ZONES">
        <div className="mb-2 text-[11px] font-mono" style={{ color: 'var(--t-muted)' }}>
          Data is split into three locked zones — AI never touches Confirmation or Unseen data.
        </div>
        <div className="grid grid-cols-1 gap-3">
          {/* Development zone */}
          <div className="p-3" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
            <span className="t-label block mb-2" style={{ color: 'var(--t-cyan)' }}>DEVELOPMENT</span>
            <div className="grid grid-cols-2 gap-3">
              <Field label="START DATE" hint="YYYY-MM-DD">
                <TInput value={fmtDate(settings.research_development_start)} onChange={v => patch({ research_development_start: unfmtDate(v) })} placeholder="2024-06-01" />
              </Field>
              <Field label="END DATE" hint="YYYY-MM-DD">
                <TInput value={fmtDate(settings.research_development_end)} onChange={v => patch({ research_development_end: unfmtDate(v) })} placeholder="2025-09-30" />
              </Field>
            </div>
            <div className="text-[10px] font-mono mt-1.5" style={{ color: 'var(--t-muted)' }}>
              Used for Pair Discovery · Hyperopt · AI Research Loop
            </div>
          </div>
          {/* Confirmation zone */}
          <div className="p-3" style={{ background: 'rgba(255,184,0,0.03)', border: '1px solid var(--t-border)' }}>
            <span className="t-label block mb-2" style={{ color: 'var(--t-yellow)' }}>CONFIRMATION</span>
            <div className="grid grid-cols-2 gap-3">
              <Field label="START DATE" hint="YYYY-MM-DD">
                <TInput value={fmtDate(settings.research_confirmation_start)} onChange={v => patch({ research_confirmation_start: unfmtDate(v) })} placeholder="2025-10-01" />
              </Field>
              <Field label="END DATE" hint="YYYY-MM-DD">
                <TInput value={fmtDate(settings.research_confirmation_end)} onChange={v => patch({ research_confirmation_end: unfmtDate(v) })} placeholder="2025-12-31" />
              </Field>
            </div>
            <div className="text-[10px] font-mono mt-1.5" style={{ color: 'var(--t-muted)' }}>
              One final check after Sensitivity · Never used for tuning
            </div>
          </div>
          {/* Final Unseen zone */}
          <div className="p-3" style={{ background: 'rgba(255,59,92,0.03)', border: '1px solid var(--t-border)' }}>
            <span className="t-label block mb-2" style={{ color: 'var(--t-red)' }}>FINAL UNSEEN</span>
            <div className="grid grid-cols-1 gap-3">
              <Field label="START DATE" hint="YYYY-MM-DD — end is always today">
                <TInput value={fmtDate(settings.research_unseen_start)} onChange={v => patch({ research_unseen_start: unfmtDate(v) })} placeholder="2026-01-01" />
              </Field>
            </div>
            <div className="text-[10px] font-mono mt-1.5" style={{ color: 'var(--t-muted)' }}>
              Locked completely · Never shown to AI · Never used by Hyperopt · Verdict only
            </div>
          </div>
        </div>
      </Panel>

      {/* ── Research Pipeline Defaults ────────────────────────────────── */}
      <Panel label="RESEARCH PIPELINE">
        <div className="grid grid-cols-2 gap-4">
          <Field label="MAX OPEN TRADES" hint="Fixed at 3 as per pipeline design.">
            <TNumber value={settings.research_max_open_trades} onChange={v => patch({ research_max_open_trades: v })} min={1} max={10} />
          </Field>
          <Field label="PAIR UNIVERSE SIZE" hint="Number of pairs evaluated in discovery.">
            <TNumber value={settings.research_pair_universe_size} onChange={v => patch({ research_pair_universe_size: v })} min={10} max={200} />
          </Field>
        </div>
        <Field label="SMOKE TEST PAIRS" hint="4 fixed pairs used in the initial smoke test.">
          <TInput
            value={settings.research_smoke_pairs.join(', ')}
            onChange={v => patch({ research_smoke_pairs: v.split(',').map(s => s.trim().toUpperCase()).filter(s => s.includes('/')) })}
            placeholder="BTC/USDT, ETH/USDT, BNB/USDT, SOL/USDT"
          />
        </Field>
      </Panel>

      <Panel label="OLLAMA CONNECTION">
        <Field label="BASE URL" hint="Ollama API endpoint (local default: http://localhost:11434).">
          <TInput value={settings.ollama_api_url} onChange={v => patch({ ollama_api_url: v })} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="DEFAULT MODEL">
            <TInput value={settings.ollama_model} onChange={v => patch({ ollama_model: v })} placeholder="e.g. llama3:8b" />
          </Field>
          <Field label="PROVIDER">
            <TInput value={settings.ollama_provider} onChange={v => patch({ ollama_provider: v })} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label="API KEY" hint="Leave empty for local Ollama.">
            <TInput value={settings.ollama_api_key} onChange={v => patch({ ollama_api_key: v })} />
          </Field>
          <Field label="TEMPERATURE" hint="0.1–0.3 recommended for structured JSON output.">
            <TNumber value={settings.ollama_temperature ?? 0.1} onChange={v => patch({ ollama_temperature: v })} min={0} max={1} step={0.05} />
          </Field>
        </div>
      </Panel>

      <Panel label="WORKFLOW MODELS">
        <div className="grid grid-cols-2 gap-4">
          <Field label="CHAT MODEL">
            <TInput value={settings.ollama_model_chat} onChange={v => patch({ ollama_model_chat: v })} placeholder="e.g. llama3:8b" />
          </Field>
          <Field label="AUTOQUANT MODEL">
            <TInput value={settings.ollama_model_autoquant} onChange={v => patch({ ollama_model_autoquant: v })} placeholder="e.g. qwen2.5:14b" />
          </Field>
          <Field label="STRATEGY LAB MODEL">
            <TInput value={settings.ollama_model_strategylab} onChange={v => patch({ ollama_model_strategylab: v })} placeholder="e.g. hermes3:3b" />
          </Field>
          <Field label="OPTIMIZER MODEL">
            <TInput value={settings.ollama_model_optimizer} onChange={v => patch({ ollama_model_optimizer: v })} placeholder="e.g. llama3:8b" />
          </Field>
        </div>
      </Panel>

      <Panel label="TIMEOUTS">
        <div className="grid grid-cols-2 gap-4">
          <Field label="DEFAULT (s)">
            <TNumber value={settings.ollama_timeout} onChange={v => patch({ ollama_timeout: v })} />
          </Field>
          <Field label="CHAT (s)">
            <TNumber value={settings.ollama_timeout_chat} onChange={v => patch({ ollama_timeout_chat: v })} />
          </Field>
          <Field label="GENERATE (s)">
            <TNumber value={settings.ollama_timeout_generate} onChange={v => patch({ ollama_timeout_generate: v })} />
          </Field>
          <Field label="AUTOQUANT (s)">
            <TNumber value={settings.ollama_timeout_autoquant} onChange={v => patch({ ollama_timeout_autoquant: v })} />
          </Field>
        </div>
      </Panel>

      <Panel label="RELIABILITY">
        <div className="grid grid-cols-2 gap-4">
          <Field label="HYPEROPT WORKERS">
            <TNumber value={settings.hyperopt_workers} onChange={v => patch({ hyperopt_workers: v })} min={1} />
          </Field>
          <Field label="RETRY DELAYS (comma-separated seconds)">
            <TInput value={settings.ollama_retry_delays.join(', ')} onChange={v => patch({ ollama_retry_delays: v.split(',').map(x => parseInt(x.trim(), 10) || 0).filter(Boolean) })} />
          </Field>
          <Field label="CIRCUIT BREAKER THRESHOLD">
            <TNumber value={settings.ollama_circuit_breaker_threshold} onChange={v => patch({ ollama_circuit_breaker_threshold: v })} />
          </Field>
          <Field label="CIRCUIT BREAKER COOLDOWN (s)">
            <TNumber value={settings.ollama_circuit_breaker_cooldown} onChange={v => patch({ ollama_circuit_breaker_cooldown: v })} />
          </Field>
          <Field label="HEALTH CHECK INTERVAL (s)">
            <TNumber value={settings.ollama_health_check_interval} onChange={v => patch({ ollama_health_check_interval: v })} />
          </Field>
          <Field label="CONNECTION POOL SIZE">
            <TNumber value={settings.ollama_connection_pool_size} onChange={v => patch({ ollama_connection_pool_size: v })} />
          </Field>
          <Field label="KEEPALIVE (s)">
            <TNumber value={settings.ollama_connection_keepalive} onChange={v => patch({ ollama_connection_keepalive: v })} />
          </Field>
        </div>
        <div className="flex items-center justify-between pt-2">
          <span className="text-xs font-mono" style={{ color: 'var(--t-text)' }}>Enable Ollama health check</span>
          <TSwitch checked={settings.ollama_enable_health_check} onChange={v => patch({ ollama_enable_health_check: v })} />
        </div>
      </Panel>

      <Panel label="WORKFLOW FLAGS">
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono" style={{ color: 'var(--t-text)' }}>Self-healing (Ollama auto-retry)</span>
          <TSwitch checked={settings.ollama_self_healing_enabled} onChange={v => patch({ ollama_self_healing_enabled: v })} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono" style={{ color: 'var(--t-text)' }}>AI assistant sandbox mode</span>
          <TSwitch checked={settings.ai_assistant_sandbox_enabled} onChange={v => patch({ ai_assistant_sandbox_enabled: v })} />
        </div>
      </Panel>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button onClick={save} disabled={!backendSettingsDirty}
          className="flex items-center gap-2 px-5 py-2.5 text-sm font-mono font-bold transition-all disabled:opacity-40"
          style={{ background: 'rgba(0,229,255,0.08)', border: '1px solid var(--t-border-hi)', color: 'var(--t-cyan)' }}
          onMouseEnter={e => !backendSettingsDirty && (e.currentTarget.style.background = 'rgba(0,229,255,0.15)')}
          onMouseLeave={e => !backendSettingsDirty && (e.currentTarget.style.background = 'rgba(0,229,255,0.08)')}>
          {saved ? <Check size={13} /> : backendSettingsLoading ? <Loader2 size={13} className="animate-spin" /> : null}
          {saved ? 'SAVED' : backendSettingsLoading ? 'LOADING...' : 'SAVE SETTINGS'}
        </button>
        <button onClick={() => load(0)}
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-mono transition-all"
          style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)', background: 'transparent' }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--t-border-hi)')}
          onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--t-border)')}>
          <RotateCcw size={12} /> RELOAD FROM BACKEND
        </button>
      </div>

      {/* Integration guide */}
      <div className="p-4" style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid var(--t-border)' }}>
        <span className="text-[10px] font-mono font-bold mb-2 block" style={{ color: 'var(--t-cyan)' }}>{'// INTEGRATION NOTES'}</span>
        {[
          'Settings are read from /api/settings and persisted with POST /api/settings',
          'Research data zones are locked — AI never sees Confirmation or Unseen data',
          'Backend validates paths and reloads services immediately after save',
          'Ollama temperature 0.1–0.3 produces more reliable structured JSON proposals',
        ].map((line, i) => (
          <div key={i} className="text-xs font-mono" style={{ color: 'var(--t-muted)' }}>{i + 1}. {line}</div>
        ))}
      </div>
    </div>
  );
}
