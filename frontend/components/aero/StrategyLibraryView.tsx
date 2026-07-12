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
  { name: 'Source Strategy', status: 'pending', paths: {}, message: 'Official strategies are read from user_data/strategies.', technical_details: {} },
  { name: 'Candidate Copy', status: 'pending', paths: {}, message: 'Candidate tests use copied strategy files in the run folder.', technical_details: {} },
  { name: 'Freqtrade Execution', status: 'pending', paths: {}, message: 'Freqtrade runs the copied candidate with --strategy-path.', technical_details: {} },
  { name: 'Metrics Parsing', status: 'pending', paths: {}, message: 'Metrics appear after candidate output artifacts are parsed.', technical_details: {} },
  { name: 'Decision', status: 'pending', paths: {}, message: 'Decisions are based on metrics and reason codes.', technical_details: {} },
  { name: 'Next Action', status: 'pending', paths: {}, message: 'Start a DEVELOP test to populate this flow.', technical_details: {} },
];

const EMPTY_FLOW_MESSAGE = 'No candidate has been created yet. Select a strategy and start a DEVELOP test to populate this flow.';

const WARNING_COPY: Record<string, string> = {
  MISSING_JSON: 'This strategy is missing its JSON sidecar file.',
  CLASS_FILE_MISMATCH: 'The Python class name does not match the strategy file name.',
  JSON_STRATEGY_NAME_MISMATCH: 'The JSON strategy_name does not match the Python strategy class.',
  EMPTY_JSON_BUY_SELL_WITH_PYTHON_PARAMS: 'The JSON buy/sell parameter blocks are empty, but the Python file defines tunable parameters.',
  PARAMS_NOT_RUNTIME_EXECUTABLE: 'Some detected parameters cannot be changed safely through the JSON sidecar yet.',
  PYTHON_ONLY_PARAMS: 'These parameters exist in the Python strategy but are missing from the JSON sidecar.',
  JSON_ONLY_PARAMS: 'These JSON runtime parameters do not have matching Python declarations.',
  PYTHON_PARSE_ERROR: 'The Python strategy file could not be parsed.',
  JSON_PARSE_ERROR: 'The JSON sidecar could not be parsed.',
};

export function readableStrategyWarning(warning: StrategyLibraryWarning): string {
  return WARNING_COPY[warning.code] ?? warning.message;
}

function stepSentence(step: AutoQuantFlowStep): string {
  switch (step.name) {
    case 'Source Strategy':
      return 'Official .py and .json files come from user_data/strategies.';
    case 'Candidate Copy':
      return 'AutoQuant tests copied candidate files, never the official files.';
    case 'Freqtrade Execution':
      return 'Freqtrade must use --strategy-path so it runs the candidate copy.';
    case 'Metrics Parsing':
      return 'Parsed artifacts become metrics for the decision.';
    case 'Decision':
      return 'The final label follows metrics plus reason codes.';
    case 'Next Action':
      return 'The next action explains what should happen after the decision.';
    default:
      return step.message || 'Step details are available below.';
  }
}

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
      <SourceTruthNotice />
      <StrategyLibraryTable scan={scan} error={error} />
      <CandidateExecutionTimeline flow={flow?.candidate ?? null} message={flow?.message ?? null} />
    </div>
  );
}

function SourceTruthNotice() {
  return (
    <section className="t-card p-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-[11px] font-mono" data-testid="source-truth-notice">
      <SourceTruthItem
        label="Official strategy source"
        value="user_data/strategies"
        detail="The library is the source of truth and is not mutated by candidate tests."
      />
      <SourceTruthItem
        label="Temporary candidate source"
        value="user_data/aeroing4/runs/<run_id>/candidates/<candidate_id>"
        detail="AutoQuant tests copied .py and .json files from the run folder."
      />
      <SourceTruthItem
        label="Execution rule"
        value="freqtrade --strategy-path"
        detail="Decisions use parsed metrics plus reason codes from the candidate run."
      />
    </section>
  );
}

function SourceTruthItem({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="space-y-1 min-w-0">
      <span className="t-label block">{label}</span>
      <span className="block truncate" title={value} style={{ color: 'var(--t-cyan)' }}>{value}</span>
      <p className="text-[10px] leading-relaxed" style={{ color: 'var(--t-muted)' }}>{detail}</p>
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
            <span>.PY FILE</span>
            <span>.JSON SIDECAR</span>
            <span>CLASS NAME</span>
            <span>JSON NAME</span>
            <span>TIMEFRAME</span>
            <span>PY PARAMS</span>
            <span>RUNTIME PARAMS</span>
          </div>
          {strategies.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs font-mono" style={{ color: 'var(--t-muted)' }}>No strategy files found.</div>
          ) : strategies.map((item) => (
            <StrategyLibraryRow key={item.strategy_name} item={item} sourceDir={scan?.strategies_dir ?? 'user_data/strategies'} />
          ))}
        </div>
      </div>
    </section>
  );
}

function StrategyLibraryRow({ item, sourceDir }: { item: StrategyLibraryItem; sourceDir: string }) {
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
          <span className="t-label block">Source: Official Library</span>
          <PathLine label="library" value={sourceDir} />
          <PathLine label=".py file" value={item.python_path} />
          <PathLine label=".json sidecar" value={item.json_path} />
          <PathLine label="class name" value={item.class_name} />
          <PathLine label="timeframe" value={item.timeframe} />
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
  const reasonCodes = flow ? flow.reason_codes : [];

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

      <div className="px-3 py-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-[10px] font-mono" style={{ borderBottom: '1px solid var(--t-border)' }}>
        <FlowFact label="Official source" value="user_data/strategies" />
        <FlowFact label="Candidate copy" value="user_data/aeroing4/runs/<run_id>/candidates/<candidate_id>" />
        <FlowFact label="Execution" value="Freqtrade uses --strategy-path for the candidate copy." />
      </div>

      {!flow && (
        <div className="px-3 py-3 text-xs font-mono" data-testid="candidate-flow-empty-state" style={{ color: 'var(--t-yellow)', borderBottom: '1px solid var(--t-border)' }}>
          {EMPTY_FLOW_MESSAGE}
          {message ? <span className="block mt-1 text-[10px]" style={{ color: 'var(--t-muted)' }}>Backend: {message}</span> : null}
        </div>
      )}

      {flow && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-px text-[10px] font-mono" style={{ background: 'var(--t-border)', borderBottom: '1px solid var(--t-border)' }}>
          <SummaryCell label="OFFICIAL PY" value={flow.official_source_strategy_path} />
          <SummaryCell label="OFFICIAL JSON" value={flow.official_source_json_path} />
          <SummaryCell label="CANDIDATE DIR" value={flow.candidate_directory} />
          <SummaryCell label="CANDIDATE PY" value={flow.copied_candidate_py} />
          <SummaryCell label="CANDIDATE JSON" value={flow.copied_candidate_json} />
          <SummaryCell label="STRATEGY PATH" value={flow.strategy_path_argument} />
          <SummaryCell label="OUTPUT ZIP" value={flow.output_zip_path} />
          <SummaryCell label="DECISION" value={flow.decision} />
        </div>
      )}

      <div className="p-3 space-y-2">
        {steps.map((step, index) => (
          <FlowStepCard key={`${step.name}-${index}`} step={step} index={index + 1} />
        ))}
      </div>

      {flow && (
        <div className="px-3 pb-3 grid grid-cols-1 lg:grid-cols-4 gap-3 text-[11px] font-mono">
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
          <div className="space-y-1">
            <span className="t-label block">DECISION REASONS</span>
            <DecisionBadge decision={flow.decision} />
            {reasonCodes.length ? (
              <div className="flex flex-wrap gap-1 pt-1">
                {reasonCodes.map((code) => (
                  <span key={code} className="px-1.5 py-0.5" style={{ border: '1px solid var(--t-border)', color: 'var(--t-label)' }}>{code}</span>
                ))}
              </div>
            ) : <span style={{ color: 'var(--t-muted)' }}>No reason codes captured.</span>}
          </div>
        </div>
      )}
    </section>
  );
}

function FlowFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="t-label block">{label}</span>
      <span className="block truncate" title={value} style={{ color: 'var(--t-muted)' }}>{value}</span>
    </div>
  );
}

function FlowStepCard({ step, index }: { step: AutoQuantFlowStep; index: number }) {
  const status = step.status === 'done' ? 'done' : step.status === 'error' ? 'error' : 'pending';
  const color = status === 'done' ? 'var(--t-green)' : status === 'error' ? 'var(--t-red)' : 'var(--t-muted)';
  const Icon = status === 'done' ? CheckCircle2 : status === 'error' ? XCircle : Clock;
  const paths = Object.entries(step.paths ?? {}).filter(([, value]) => value);
  const sentence = stepSentence(step);
  const technicalDetails = { message: step.message, ...(step.technical_details ?? {}) };

  return (
    <details data-testid="candidate-flow-step-card" className="group" style={{ border: '1px solid var(--t-border)', background: 'var(--t-bg)' }}>
      <summary className="flex items-center gap-3 px-3 py-2 cursor-pointer list-none">
        <span className="w-6 h-6 flex items-center justify-center text-[10px] font-mono" style={{ color, border: `1px solid ${color}` }}>{index}</span>
        <Icon size={13} style={{ color }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-semibold" style={{ color: 'var(--t-text)' }}>{step.name.toUpperCase()}</span>
            <StatusBadge status={step.status} />
          </div>
          <p className="text-[10px] font-mono truncate" style={{ color: 'var(--t-muted)' }}>{sentence}</p>
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
            {JSON.stringify(technicalDetails, null, 2)}
          </code>
        </div>
      </div>
    </details>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status === 'done' ? 'done' : status === 'error' ? 'error' : status === 'warning' ? 'warning' : 'pending';
  const color =
    normalized === 'done' ? 'var(--t-green)' :
    normalized === 'error' ? 'var(--t-red)' :
    normalized === 'warning' ? 'var(--t-yellow)' :
    'var(--t-muted)';
  return (
    <span className="px-1.5 py-0.5 text-[10px] font-mono" style={{ color, border: `1px solid ${color}` }}>
      {String(status).toUpperCase()}
    </span>
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
          <span style={{ color: warning.severity === 'error' ? 'var(--t-red)' : 'var(--t-yellow)' }}>
            <span className="font-semibold">{warning.code}</span>: {readableStrategyWarning(warning)}
            {warning.message && warning.message !== readableStrategyWarning(warning) ? (
              <span className="block text-[10px]" style={{ color: 'var(--t-muted)' }}>{warning.message}</span>
            ) : null}
          </span>
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
