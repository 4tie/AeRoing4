'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, FileCode2, GitBranch, XCircle } from 'lucide-react';
import {
  getLatestAutoQuantFlow,
  getStrategyLibraryScan,
  type AutoQuantCandidateFlow,
  type AutoQuantFlowResponse,
  type AutoQuantFlowStep,
  type StrategyLibraryItem,
  type StrategyLibraryParameter,
  type StrategyLibraryScan,
  type StrategyLibraryWarning,
} from '@/lib/api';

const EMPTY_FLOW_STEPS: AutoQuantFlowStep[] = [
  { name: 'Source Strategy', status: 'pending', paths: {}, message: 'Waiting for a candidate run.', technical_details: {} },
  { name: 'Candidate Copy', status: 'pending', paths: {}, message: 'Waiting for a candidate run.', technical_details: {} },
  { name: 'Freqtrade Execution', status: 'pending', paths: {}, message: 'Waiting for a candidate run.', technical_details: {} },
  { name: 'Metrics Parsing', status: 'pending', paths: {}, message: 'Waiting for a candidate run.', technical_details: {} },
  { name: 'Decision', status: 'pending', paths: {}, message: 'Waiting for a candidate run.', technical_details: {} },
  { name: 'Next Action', status: 'pending', paths: {}, message: 'Waiting for a candidate run.', technical_details: {} },
];

export function StrategyLibraryView() {
  const [scan, setScan] = useState<StrategyLibraryScan | null>(null);
  const [flow, setFlow] = useState<AutoQuantFlowResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getStrategyLibraryScan(), getLatestAutoQuantFlow()])
      .then(([scanData, flowData]) => {
        if (!alive) return;
        setScan(scanData);
        setFlow(flowData);
        setError(null);
      })
      .catch((exc) => {
        if (!alive) return;
        setError(exc instanceof Error ? exc.message : 'Source-of-truth load failed');
      });
    return () => { alive = false; };
  }, []);

  return (
    <div className="space-y-4">
      <StrategyLibraryTable scan={scan} error={error} />
      <CandidateExecutionTimeline flow={flow?.candidate ?? null} message={flow?.message ?? null} />
    </div>
  );
}

export function StrategyLibraryTable({ scan, error }: { scan: StrategyLibraryScan | null; error?: string | null }) {
  const strategies = scan?.strategies ?? [];
  const warningCount = strategies.reduce((count, item) => count + item.warnings.length, 0);

  return (
    <section className="t-card overflow-hidden" data-testid="strategy-library-view">
      <div className="px-3 py-2 flex items-center justify-between gap-3" style={{ borderBottom: '1px solid var(--t-border)' }}>
        <div className="flex items-center gap-2 min-w-0">
          <FileCode2 size={14} style={{ color: 'var(--t-cyan)' }} />
          <span className="t-label">STRATEGY LIBRARY</span>
          <span className="text-[10px] font-mono truncate" style={{ color: 'var(--t-muted)' }}>{scan?.strategies_dir ?? 'user_data/strategies'}</span>
        </div>
        <div className="flex items-center gap-2 text-[10px] font-mono">
          <span style={{ color: 'var(--t-text)' }}>{strategies.length} strategies</span>
          <span style={{ color: warningCount ? 'var(--t-yellow)' : 'var(--t-green)' }}>{warningCount} warnings</span>
        </div>
      </div>

      {error && (
        <div className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--t-red)', borderBottom: '1px solid var(--t-border)' }}>
          {error}
        </div>
      )}

      <div className="overflow-x-auto">
        <div className="min-w-[980px]">
          <div className="grid grid-cols-[1.35fr_70px_70px_1fr_1fr_90px_110px_120px] gap-2 px-3 py-2 text-[10px] font-mono" style={{ color: 'var(--t-label)', borderBottom: '1px solid var(--t-border)' }}>
            <span>STRATEGY</span>
            <span>.PY</span>
            <span>.JSON</span>
            <span>CLASS</span>
            <span>JSON NAME</span>
            <span>TIMEFRAME</span>
            <span>PY PARAMS</span>
            <span>RUNTIME PARAMS</span>
          </div>
          {strategies.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs font-mono" style={{ color: 'var(--t-muted)' }}>No strategy files found.</div>
          ) : strategies.map((item) => (
            <StrategyLibraryRow key={item.strategy_name} item={item} />
          ))}
        </div>
      </div>
    </section>
  );
}

function StrategyLibraryRow({ item }: { item: StrategyLibraryItem }) {
  const warningCodes = item.warnings.map((w) => w.code);
  return (
    <details data-testid="strategy-library-row" className="group" style={{ borderBottom: '1px solid var(--t-border)' }}>
      <summary className="grid grid-cols-[1.35fr_70px_70px_1fr_1fr_90px_110px_120px] gap-2 px-3 py-2 cursor-pointer list-none text-xs font-mono items-center">
        <span className="truncate" style={{ color: item.warnings.length ? 'var(--t-yellow)' : 'var(--t-text)' }}>{item.strategy_name}</span>
        <BoolBadge value={item.py_exists} />
        <BoolBadge value={item.json_exists} />
        <span className="truncate" style={{ color: item.class_name && item.class_name !== item.strategy_name ? 'var(--t-yellow)' : 'var(--t-text)' }}>{item.class_name ?? '-'}</span>
        <span className="truncate" style={{ color: warningCodes.includes('JSON_STRATEGY_NAME_MISMATCH') ? 'var(--t-yellow)' : 'var(--t-text)' }}>{item.json_strategy_name ?? '-'}</span>
        <span style={{ color: 'var(--t-cyan)' }}>{item.timeframe ?? '-'}</span>
        <span style={{ color: item.python_only_params.length ? 'var(--t-yellow)' : 'var(--t-text)' }}>
          {item.python_parameters.length} total
        </span>
        <span style={{ color: item.json_only_params.length ? 'var(--t-yellow)' : 'var(--t-text)' }}>
          {item.json_runtime_params.length} total
        </span>
      </summary>
      <div className="px-3 pb-3 grid grid-cols-1 lg:grid-cols-3 gap-3 text-[11px] font-mono" style={{ background: 'rgba(0,0,0,0.18)' }}>
        <div className="space-y-2">
          <span className="t-label block">FILES</span>
          <PathLine label="py" value={item.python_path} />
          <PathLine label="json" value={item.json_path} />
          <WarningList warnings={item.warnings} />
        </div>
        <div className="space-y-2">
          <span className="t-label block">PYTHON PARAMETERS</span>
          <ParamList params={item.python_parameters} empty="No Python tunables detected." />
          <DiffLine label="python-only" values={item.python_only_params} />
        </div>
        <div className="space-y-2">
          <span className="t-label block">JSON RUNTIME PARAMS</span>
          <ParamList params={item.json_runtime_params} empty="No JSON runtime params detected." />
          <DiffLine label="json-only" values={item.json_only_params} />
        </div>
      </div>
    </details>
  );
}

export function CandidateExecutionTimeline({ flow, message }: { flow: AutoQuantCandidateFlow | null; message?: string | null }) {
  const steps = flow?.steps?.length ? flow.steps : EMPTY_FLOW_STEPS;
  const metrics = useMemo(() => Object.entries(flow?.parsed_metrics ?? {}), [flow]);

  return (
    <section className="t-card overflow-hidden" data-testid="candidate-flow-view">
      <div className="px-3 py-2 flex items-center justify-between gap-3" style={{ borderBottom: '1px solid var(--t-border)' }}>
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch size={14} style={{ color: 'var(--t-green)' }} />
          <span className="t-label">AUTOQUANT FLOW</span>
          <span className="text-[10px] font-mono truncate" style={{ color: 'var(--t-muted)' }}>{flow?.run_id ?? message ?? 'No candidate yet'}</span>
        </div>
        <DecisionBadge decision={flow?.decision ?? 'INCONCLUSIVE'} faded={!flow} />
      </div>

      {flow && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-px text-[10px] font-mono" style={{ background: 'var(--t-border)', borderBottom: '1px solid var(--t-border)' }}>
          <SummaryCell label="OFFICIAL PY" value={flow.official_source_strategy_path} />
          <SummaryCell label="OFFICIAL JSON" value={flow.official_source_json_path} />
          <SummaryCell label="CANDIDATE DIR" value={flow.candidate_directory} />
          <SummaryCell label="OUTPUT ZIP" value={flow.output_zip_path} />
        </div>
      )}

      <div className="p-3 space-y-2">
        {steps.map((step, index) => (
          <FlowStepCard key={`${step.name}-${index}`} step={step} index={index + 1} />
        ))}
      </div>

      {flow && (
        <div className="px-3 pb-3 grid grid-cols-1 lg:grid-cols-3 gap-3 text-[11px] font-mono">
          <div className="space-y-1">
            <span className="t-label block">COMMAND</span>
            <code className="block p-2 whitespace-pre-wrap break-all" style={{ color: 'var(--t-muted)', background: 'var(--t-bg)', border: '1px solid var(--t-border)' }}>
              {flow.freqtrade_command ?? 'not captured'}
            </code>
          </div>
          <div className="space-y-1">
            <span className="t-label block">ARTIFACT CHECKS</span>
            <CheckLine label="official unchanged" value={flow.official_files_unchanged} />
            <CheckLine label="--strategy-path run/candidate" value={flow.strategy_path_points_to_candidate_or_run_dir} />
            <CheckLine label="zip contains .py" value={flow.output_zip_contains_py} />
            <CheckLine label="zip contains .json" value={flow.output_zip_contains_json} />
          </div>
          <div className="space-y-1">
            <span className="t-label block">PARSED METRICS</span>
            {metrics.length ? metrics.map(([key, value]) => (
              <div key={key} className="flex justify-between gap-2">
                <span style={{ color: 'var(--t-muted)' }}>{key}</span>
                <span style={{ color: 'var(--t-text)' }}>{formatValue(value)}</span>
              </div>
            )) : <span style={{ color: 'var(--t-muted)' }}>No parsed metrics.</span>}
          </div>
        </div>
      )}
    </section>
  );
}

function FlowStepCard({ step, index }: { step: AutoQuantFlowStep; index: number }) {
  const status = step.status === 'done' ? 'done' : step.status === 'error' ? 'error' : 'pending';
  const color = status === 'done' ? 'var(--t-green)' : status === 'error' ? 'var(--t-red)' : 'var(--t-muted)';
  const Icon = status === 'done' ? CheckCircle2 : status === 'error' ? XCircle : Clock;
  const paths = Object.entries(step.paths ?? {}).filter(([, value]) => value);

  return (
    <details data-testid="candidate-flow-step-card" className="group" style={{ border: '1px solid var(--t-border)', background: 'var(--t-bg)' }}>
      <summary className="flex items-center gap-3 px-3 py-2 cursor-pointer list-none">
        <span className="w-6 h-6 flex items-center justify-center text-[10px] font-mono" style={{ color, border: `1px solid ${color}` }}>{index}</span>
        <Icon size={13} style={{ color }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-semibold" style={{ color: 'var(--t-text)' }}>{step.name.toUpperCase()}</span>
            <span className="text-[10px] font-mono" style={{ color }}>{String(step.status).toUpperCase()}</span>
          </div>
          <p className="text-[10px] font-mono truncate" style={{ color: 'var(--t-muted)' }}>{step.message}</p>
        </div>
      </summary>
      <div className="px-3 pb-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px] font-mono">
        <div className="space-y-1">
          <span className="t-label block">PATHS USED</span>
          {paths.length ? paths.map(([key, value]) => <PathLine key={key} label={key} value={value} />) : <span style={{ color: 'var(--t-muted)' }}>No paths captured.</span>}
        </div>
        <div className="space-y-1">
          <span className="t-label block">TECHNICAL DETAILS</span>
          <code className="block p-2 whitespace-pre-wrap break-all" style={{ color: 'var(--t-muted)', background: '#050505', border: '1px solid var(--t-border)' }}>
            {JSON.stringify(step.technical_details ?? {}, null, 2)}
          </code>
        </div>
      </div>
    </details>
  );
}

function BoolBadge({ value }: { value: boolean }) {
  return (
    <span className="text-[10px] font-mono" style={{ color: value ? 'var(--t-green)' : 'var(--t-red)' }}>
      {value ? 'yes' : 'no'}
    </span>
  );
}

function DecisionBadge({ decision, faded }: { decision: string; faded?: boolean }) {
  const color =
    decision === 'KEEP' ? 'var(--t-green)' :
    decision === 'DROP' ? 'var(--t-red)' :
    decision === 'REJECTED' ? 'var(--t-red)' :
    'var(--t-yellow)';
  return (
    <span className="px-2 py-1 text-[10px] font-mono font-bold" style={{ color, opacity: faded ? 0.45 : 1, border: `1px solid ${color}` }}>
      {decision}
    </span>
  );
}

function WarningList({ warnings }: { warnings: StrategyLibraryWarning[] }) {
  if (!warnings.length) return <span className="text-[10px]" style={{ color: 'var(--t-green)' }}>No warnings.</span>;
  return (
    <div className="space-y-1" data-testid="strategy-warning-list">
      {warnings.map((warning) => (
        <div key={`${warning.code}-${warning.message}`} className="flex gap-2">
          <AlertTriangle size={11} className="shrink-0 mt-0.5" style={{ color: warning.severity === 'error' ? 'var(--t-red)' : 'var(--t-yellow)' }} />
          <span style={{ color: warning.severity === 'error' ? 'var(--t-red)' : 'var(--t-yellow)' }}>{warning.code}: {warning.message}</span>
        </div>
      ))}
    </div>
  );
}

function ParamList({ params, empty }: { params: StrategyLibraryParameter[]; empty: string }) {
  if (!params.length) return <span style={{ color: 'var(--t-muted)' }}>{empty}</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {params.map((param) => (
        <span key={`${param.source}-${param.runtime_path ?? param.name}`} className="px-1.5 py-0.5" style={{ border: '1px solid var(--t-border)', color: param.runtime_executable ? 'var(--t-green)' : 'var(--t-yellow)' }}>
          {param.name}{param.space ? `:${param.space}` : ''}
        </span>
      ))}
    </div>
  );
}

function DiffLine({ label, values }: { label: string; values: string[] }) {
  return (
    <div data-testid={`strategy-${label}-warning`}>
      <span style={{ color: values.length ? 'var(--t-yellow)' : 'var(--t-muted)' }}>{label}: </span>
      <span style={{ color: values.length ? 'var(--t-yellow)' : 'var(--t-muted)' }}>{values.length ? values.join(', ') : 'none'}</span>
    </div>
  );
}

function PathLine({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-[95px_1fr] gap-2 min-w-0">
      <span style={{ color: 'var(--t-muted)' }}>{label}</span>
      <span className="truncate" title={value ?? ''} style={{ color: value ? 'var(--t-text)' : 'var(--t-muted)' }}>{value ?? '-'}</span>
    </div>
  );
}

function SummaryCell({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="p-2 min-w-0" style={{ background: 'var(--t-card)' }}>
      <span className="t-label block">{label}</span>
      <span className="block truncate" title={value ?? ''} style={{ color: value ? 'var(--t-text)' : 'var(--t-muted)' }}>{value ?? '-'}</span>
    </div>
  );
}

function CheckLine({ label, value }: { label: string; value?: boolean | null }) {
  const color = value == null ? 'var(--t-muted)' : value ? 'var(--t-green)' : 'var(--t-red)';
  return (
    <div className="flex justify-between gap-2">
      <span style={{ color: 'var(--t-muted)' }}>{label}</span>
      <span style={{ color }}>{value == null ? 'unknown' : value ? 'yes' : 'no'}</span>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (value == null) return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
