/**
 * AeRo API layer — real fetch calls to the FastAPI backend.
 *
 * API_BASE_URL targets 127.0.0.1:8000 (local workspace only).
 * All types that components depend on are exported from here;
 * mockApi.ts has been removed.
 */

// ── Base URL ──────────────────────────────────────────────────────────────────

// Empty string = same-origin: Next.js rewrites /api/* → backend (port 8000).
// This works in both the browser and Replit's proxy without hardcoding ports.
export const API_BASE_URL = '';

// ── Shared types ──────────────────────────────────────────────────────────────

export interface Strategy {
  name: string;
  timeframe: string;
  stoploss: number;
  roi: { minutes: number; roi: number }[];
  indicators: string[];
}

export interface Trade {
  timestamp: string;
  pair: string;
  side: 'long' | 'short';
  profit: number;
  duration: string;
}

export interface StrategyDetail extends Strategy {
  trades: Trade[];
  equity: { time: string; value: number }[];
}

export interface RiskMetrics {
  maxDrawdown: number;
  winRate: number;
  sharpe: number;
  lossBullets: string[];
}

export interface BacktestResult {
  totalTrades: number;
  winRate: number;
  profitPct: number;
  drawdown: number;
  finalEquity: number;
}

export interface PipelineRun {
  id: string;
  createdAt: string;
  status: 'pending' | 'running' | 'done' | 'error';
  currentStage: number;
  stages: StageStatus[];
}

export interface StageStatus {
  id: number;
  name: string;
  status: 'pending' | 'running' | 'done' | 'error';
  progress: number;
  logs: string[];
}

// ── AeRoing4 types ────────────────────────────────────────────────────────────

export type PairStatus =
  | 'VALID_CANDIDATE'
  | 'ZERO_TRADES'
  | 'INSUFFICIENT_TRADES'
  | 'DATA_UNAVAILABLE'
  | 'EXECUTION_FAILURE';

export interface DiscoveryPairResult {
  pair: string;
  rank: number | null;
  rank_score: number | null;
  status: PairStatus;
  rejection_reasons: string[];
  total_trades: number | null;
  net_profit: number | null;
  net_profit_pct: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  average_trade_duration: string | null;
  backtest_run_id: string;
  score_inputs: {
    trade_sufficiency_score: number | null;
    expectancy_score: number | null;
    profit_factor_score: number | null;
    drawdown_penalty: number | null;
    net_profit_score: number | null;
  } | null;
}

export interface PairDiscoveryResult {
  universe_size: number;
  usable_pairs: number;
  evaluated_pairs: number;
  valid_candidates: number;
  rejected_pairs: number;
  discovery_timerange: string;
  discovery_pairs: string[];
  ranking_policy_version: string;
  ranked_pairs: DiscoveryPairResult[];
}

export type WorkflowStepStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped';

export interface WorkflowStep {
  id: string;
  name: string;
  status: WorkflowStepStatus;
  progress: number;
  logs: string[];
}

export type SmokeOutcome =
  | 'PASS_ACTIVITY'
  | 'NO_SIGNAL_ACTIVITY'
  | 'EXECUTION_FAILURE'
  | null;

export interface AeRoing4RunState {
  id: string;
  created_at: string;
  strategy_name: string;
  strategy_timeframe: string;
  discovery_pairs: string[];
  discovery_timerange: string;
  smoke_timerange: string;
  enable_pair_discovery: boolean;
  status: 'pending' | 'running' | 'done' | 'error';
  outcome: 'IN_PROGRESS' | 'SUCCESS' | 'NO_PAIR_CANDIDATES' | 'EXECUTION_FAILURE' | null;
  smoke_outcome: SmokeOutcome;
  steps: WorkflowStep[];
  discovery_result: PairDiscoveryResult | null;
}

export interface AeRoing4RunRequest {
  strategy_name: string;
  discovery_pairs?: string[];
  discovery_timerange?: string;
  enable_pair_discovery?: boolean;
}

export interface StrategyLibraryWarning {
  code: string;
  message: string;
  severity: string;
}

export interface StrategyLibraryParameter {
  name: string;
  source: string;
  parameter_type?: string | null;
  space?: string | null;
  default?: unknown;
  current?: unknown;
  min_value?: unknown;
  max_value?: unknown;
  choices?: unknown[] | null;
  optimizable?: boolean | null;
  runtime_path?: string | null;
  runtime_executable: boolean;
}

export interface StrategyLibraryItem {
  strategy_name: string;
  py_exists: boolean;
  json_exists: boolean;
  python_path?: string | null;
  json_path?: string | null;
  class_name?: string | null;
  json_strategy_name?: string | null;
  timeframe?: string | null;
  python_parameters: StrategyLibraryParameter[];
  json_runtime_params: StrategyLibraryParameter[];
  python_only_params: string[];
  json_only_params: string[];
  warnings: StrategyLibraryWarning[];
}

export interface StrategyLibraryScan {
  strategies_dir: string;
  strategies: StrategyLibraryItem[];
}

export interface AutoQuantFlowStep {
  name: string;
  status: 'pending' | 'done' | 'error' | 'warning' | string;
  paths: Record<string, string | null>;
  message: string;
  technical_details: Record<string, unknown>;
}

export type AutoQuantDecision = 'KEEP' | 'DROP' | 'INCONCLUSIVE' | 'REJECTED';

export interface AutoQuantCandidateFlow {
  run_id: string;
  experiment_id?: string | null;
  candidate_id?: string | null;
  strategy_name?: string | null;
  official_source_strategy_path?: string | null;
  official_source_json_path?: string | null;
  candidate_directory?: string | null;
  copied_candidate_py?: string | null;
  copied_candidate_json?: string | null;
  official_files_unchanged?: boolean | null;
  freqtrade_command?: string | null;
  strategy_path_argument?: string | null;
  strategy_path_points_to_candidate_dir: boolean;
  strategy_path_points_to_run_dir: boolean;
  strategy_path_points_to_candidate_or_run_dir: boolean;
  output_zip_path?: string | null;
  output_zip_contains_py?: boolean | null;
  output_zip_contains_json?: boolean | null;
  parsed_metrics: Record<string, unknown>;
  decision: AutoQuantDecision;
  reason_codes: string[];
  steps: AutoQuantFlowStep[];
}

export interface AutoQuantFlowResponse {
  run_id?: string | null;
  candidate?: AutoQuantCandidateFlow | null;
  message: string;
}

// ── Default discovery universe ────────────────────────────────────────────────

export const DEFAULT_DISCOVERY_UNIVERSE: string[] = [
  'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'ADA/USDT',
  'AVAX/USDT', 'DOT/USDT', 'MATIC/USDT', 'LINK/USDT', 'UNI/USDT',
  'ATOM/USDT', 'LTC/USDT', 'XRP/USDT', 'DOGE/USDT', 'NEAR/USDT',
  'APE/USDT', 'FTM/USDT', 'ALGO/USDT', 'ICP/USDT', 'ETC/USDT',
  'SAND/USDT', 'MANA/USDT', 'CRV/USDT', 'AAVE/USDT', 'SUSHI/USDT',
];

// ── Internal helpers ──────────────────────────────────────────────────────────

function mapBackendStatus(s: string): 'pending' | 'running' | 'done' | 'error' {
  if (s === 'completed' || s === 'passed') return 'done';
  if (s === 'failed' || s === 'cancelled') return 'error';
  if (s === 'running') return 'running';
  return 'pending';
}

function mapStepStatus(s: string): WorkflowStepStatus {
  // Backend emits lowercase enum values (e.g. "passed", "failed", "running", "skipped")
  const lower = s.toLowerCase();
  if (lower === 'passed' || lower === 'completed') return 'done';
  if (lower === 'failed' || lower === 'cancelled') return 'error';
  if (lower === 'running') return 'running';
  if (lower === 'skipped') return 'skipped';
  return 'pending';
}

const STEP_DISPLAY_NAMES: Record<string, string> = {
  validation: 'Strategy Validation',
  data_preparation: 'Smoke Data Prep',
  smoke_backtest: 'Smoke Backtest',
  pair_discovery: 'Pair Discovery',
};

/** Convert the backend run shape to the frontend AeRoing4RunState. */
function mapBackendRun(run: Record<string, unknown>): AeRoing4RunState {
  const rawSteps = (run.steps ?? {}) as Record<string, Record<string, unknown>>;

  // Ordered step list (backend fills steps progressively)
  const STEP_ORDER = ['validation', 'data_preparation', 'smoke_backtest', 'pair_discovery'];
  const steps: WorkflowStep[] = STEP_ORDER.map((id) => {
    const s = rawSteps[id];
    if (!s) return { id, name: STEP_DISPLAY_NAMES[id] ?? id, status: 'pending', progress: 0, logs: [] };
    const status = mapStepStatus(String(s.status ?? 'PENDING'));
    const stepData = (s.data ?? {}) as Record<string, unknown>;
    const logs: string[] = [];
    if (stepData.outcome) logs.push(`[OK] outcome: ${stepData.outcome}`);
    if (s.error) logs.push(`[ERR] ${s.error}`);
    return {
      id,
      name: STEP_DISPLAY_NAMES[id] ?? id,
      status,
      progress: status === 'done' ? 100 : status === 'running' ? 50 : 0,
      logs,
    };
  });

  // Extract smoke outcome
  const smokeStep = rawSteps.smoke_backtest;
  const smokeData = (smokeStep?.data ?? {}) as Record<string, unknown>;
  let smokeOutcome: SmokeOutcome = null;
  // Backend emits lowercase enum values (e.g. "pass_activity")
  const smokeOC = String(smokeData.outcome ?? '').toLowerCase();
  if (smokeOC === 'pass_activity') smokeOutcome = 'PASS_ACTIVITY';
  else if (smokeOC === 'no_signal_activity') smokeOutcome = 'NO_SIGNAL_ACTIVITY';
  else if (smokeOC === 'execution_failure') smokeOutcome = 'EXECUTION_FAILURE';

  // Extract discovery result
  let discoveryResult: PairDiscoveryResult | null = null;
  const discStep = rawSteps.pair_discovery;
  const discData = (discStep?.data ?? {}) as Record<string, unknown>;
  const rawDr = discData.discovery_result as Record<string, unknown> | undefined;
  if (rawDr) {
    const allEvals = (rawDr.all_evaluations ?? rawDr.ranked_pairs ?? []) as Array<Record<string, unknown>>;
    const ranked = (rawDr.ranked_pairs ?? []) as Array<Record<string, unknown>>;
    const mappedPairs: DiscoveryPairResult[] = allEvals.map((e) => {
      const sc = e.score_components as Record<string, number> | undefined;
      return {
        pair: String(e.pair ?? ''),
        rank: e.rank != null ? Number(e.rank) : null,
        rank_score: e.rank_score != null ? Number(e.rank_score) : null,
        // Backend emits lowercase; map to uppercase for UI STATUS_CFG keys
        status: String(e.status ?? 'data_unavailable').toUpperCase() as PairStatus,
        rejection_reasons: (e.rejection_reasons as string[]) ?? [],
        total_trades: e.total_trades != null ? Number(e.total_trades) : null,
        net_profit: e.net_profit_pct != null ? Number(e.net_profit_pct) * 10 : null,
        net_profit_pct: e.net_profit_pct != null ? Number(e.net_profit_pct) : null,
        profit_factor: e.profit_factor != null ? Number(e.profit_factor) : null,
        expectancy: e.expectancy != null ? Number(e.expectancy) : null,
        max_drawdown: e.max_drawdown_pct != null ? Number(e.max_drawdown_pct) : null,
        win_rate: e.win_rate != null ? Number(e.win_rate) : null,
        average_trade_duration: null,
        backtest_run_id: String(e.explorer_session_id ?? ''),
        score_inputs: sc
          ? {
              profit_factor_score: sc.pf_score ?? null,
              net_profit_score: sc.np_score ?? null,
              expectancy_score: sc.exp_score ?? null,
              drawdown_penalty: sc.dd_penalty ?? null,
              trade_sufficiency_score: sc.trade_sufficiency_multiplier ?? null,
            }
          : null,
      };
    });

    const validCount = (_mapped: DiscoveryPairResult[]) => mappedPairs.filter(p => p.status === 'VALID_CANDIDATE').length;
    discoveryResult = {
      universe_size: Number(rawDr.universe_size ?? 0),
      usable_pairs: Number(rawDr.usable_pairs_count ?? rawDr.usable_pairs ?? 0),
      evaluated_pairs: Number(rawDr.evaluated_pairs_count ?? rawDr.evaluated_pairs ?? 0),
      valid_candidates: Number(rawDr.valid_candidates_count ?? rawDr.valid_candidates ?? validCount(mappedPairs)),
      rejected_pairs: Number(rawDr.rejected_pairs_count ?? rawDr.rejected_pairs ?? 0),
      discovery_timerange: String(rawDr.discovery_timerange ?? rawDr.timerange ?? ''),
      discovery_pairs: (rawDr.discovery_pairs_requested ?? rawDr.discovery_pairs ?? []) as string[],
      ranking_policy_version: String(rawDr.ranking_policy_version ?? ''),
      ranked_pairs: mappedPairs,
    };
  }

  // Determine frontend outcome
  let outcome: AeRoing4RunState['outcome'] = null;
  const backendStatus = String(run.status ?? '');
  if (backendStatus === 'running' || backendStatus === 'pending') {
    outcome = 'IN_PROGRESS';
  } else if (backendStatus === 'completed') {
    if (discData.outcome === 'valid_candidates_found') outcome = 'SUCCESS';
    else if (discData.outcome === 'no_pair_candidates') outcome = 'NO_PAIR_CANDIDATES';
    else outcome = 'SUCCESS';
  } else if (backendStatus === 'failed') {
    outcome = 'EXECUTION_FAILURE';
  }

  return {
    id: String(run.run_id ?? ''),
    created_at: String(run.created_at ?? new Date().toISOString()),
    strategy_name: String(run.strategy_name ?? ''),
    strategy_timeframe: String(run.timeframe ?? '5m'),
    discovery_pairs: (run.discovery_pairs as string[]) ?? [],
    discovery_timerange: String(run.discovery_timerange ?? ''),
    smoke_timerange: String(run.smoke_timerange ?? ''),
    enable_pair_discovery: Boolean(run.enable_pair_discovery ?? false),
    status: mapBackendStatus(backendStatus),
    outcome,
    smoke_outcome: smokeOutcome,
    steps,
    discovery_result: discoveryResult,
  };
}

// ── API functions ─────────────────────────────────────────────────────────────

/** List all strategies from the backend — uses the files list (real stems) merged with registry metadata. */
export async function getStrategies(): Promise<Strategy[]> {
  try {
    // Files list gives us the real file stems (e.g. "sample_strategy")
    const [filesRes, metaRes] = await Promise.all([
      fetch(`${API_BASE_URL}/api/strategies/files`),
      fetch(`${API_BASE_URL}/api/strategies`),
    ]);
    const filesData = filesRes.ok
      ? (await filesRes.json() as { strategies?: Array<Record<string, unknown>> })
      : { strategies: [] };
    const metaData = metaRes.ok
      ? (await metaRes.json() as { strategies?: Array<Record<string, unknown>> })
      : { strategies: [] };

    // Build a lookup: normalised stem → timeframe from registry
    const timeframeLookup: Record<string, string> = {};
    for (const m of metaData.strategies ?? []) {
      const key = String(m.strategy_name ?? m.name ?? '').toLowerCase().replace(/[_-]/g, '');
      timeframeLookup[key] = String(m.timeframe ?? '5m');
    }

    return (filesData.strategies ?? []).map((f) => {
      const stem = String(f.name ?? '');
      const key = stem.toLowerCase().replace(/[_-]/g, '');
      return {
        name: stem,
        timeframe: timeframeLookup[key] ?? '5m',
        stoploss: -0.10,
        roi: [],
        indicators: [],
      };
    });
  } catch {
    return [];
  }
}

/** Get strategy detail — fetches file content + raw Python to parse params. */
export async function getStrategyDetail(name: string): Promise<StrategyDetail> {
  if (!name) return { name: '', timeframe: '5m', stoploss: -0.10, roi: [], indicators: [], trades: [], equity: [] };
  try {
    const [filesRes, contentRes] = await Promise.all([
      fetch(`${API_BASE_URL}/api/strategies/files/${encodeURIComponent(name)}`),
      fetch(`${API_BASE_URL}/api/strategies/content?filename=${encodeURIComponent(name)}.py`),
    ]);

    // Parse JSON params (ROI, stoploss)
    let stoploss = -0.10;
    let roi: Strategy['roi'] = [];
    let timeframe = '5m';
    let indicators: string[] = [];

    if (filesRes.ok) {
      const data = await filesRes.json() as Record<string, unknown>;
      // Extract from embedded JSON params file
      try {
        const jsonContent = typeof data.json_content === 'string'
          ? JSON.parse(data.json_content) as Record<string, unknown>
          : null;
        if (jsonContent) {
          const params = jsonContent.params as Record<string, unknown> | undefined;
          const slObj = params?.stoploss as Record<string, unknown> | undefined;
          if (slObj?.stoploss != null) stoploss = Number(slObj.stoploss);
          const roiObj = params?.roi as Record<string, unknown> | undefined;
          if (roiObj) {
            roi = Object.entries(roiObj).map(([mins, val]) => ({
              minutes: Number(mins),
              roi: Number(val),
            })).sort((a, b) => a.minutes - b.minutes);
          }
        }
      } catch { /* ignore parse errors */ }
    }

    // Extract from Python source
    if (contentRes.ok) {
      const contentData = await contentRes.json() as Record<string, unknown>;
      const src = String(contentData.content ?? contentData.file_content ?? '');
      // Extract timeframe
      const tfMatch = src.match(/timeframe\s*=\s*['"]([^'"]+)['"]/);
      if (tfMatch) timeframe = tfMatch[1];
      // Extract stoploss (override if found in py)
      const slMatch = src.match(/stoploss\s*=\s*(-[\d.]+)/);
      if (slMatch) stoploss = parseFloat(slMatch[1]);
      // Extract TA indicator names: lines like `dataframe['xxx'] = ta.SOMETHING(`
      const taRegex = /ta\.([A-Z][A-Z0-9_]*)\s*\(/g;
      const seen = new Set<string>();
      let m: RegExpExecArray | null;
      while ((m = taRegex.exec(src)) !== null) seen.add(m[1]);
      // Also pandas_ta / talib style
      const pta = /\.([a-z][a-z0-9_]+)\s*\(/g;
      while ((m = pta.exec(src)) !== null) {
        const fn = m[1].toUpperCase();
        if (['EMA','SMA','RSI','MACD','BB','ATR','ADX','STOCH','BBANDS','MFI','ROC','CCI','OBV','SAR'].includes(fn))
          seen.add(fn);
      }
      indicators = Array.from(seen);
    }

    return { name, timeframe, stoploss, roi, indicators, trades: [], equity: [] };
  } catch { /* fall through */ }
  return { name, timeframe: '5m', stoploss: -0.10, roi: [], indicators: [], trades: [], equity: [] };
}

/** Upload a strategy file to the backend. */
export async function uploadStrategy(file: File): Promise<{ ok: boolean; name: string }> {
  const name = file.name.replace(/\.py$/, '');
  try {
    const content = await file.text();
    const res = await fetch(`${API_BASE_URL}/api/strategies/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content }),
    });
    return { ok: res.ok, name };
  } catch {
    return { ok: false, name };
  }
}

/** Risk metrics — derived from latest AeRoing4 run or strategy JSON params. */
export async function getRiskMetrics(strategyName: string): Promise<RiskMetrics> {
  try {
    // Try to pull from existing AeRoing4 runs for this strategy
    const runsRes = await fetch(`${API_BASE_URL}/api/aeroing4/runs?limit=10`);
    if (runsRes.ok) {
      const runsData = await runsRes.json() as { runs?: Array<Record<string, unknown>> };
      const match = (runsData.runs ?? []).find(
        (r) => String(r.strategy_name ?? '').toLowerCase() === strategyName.toLowerCase()
      );
      if (match) {
        // Pull from smoke/discovery step data if available
        const steps = (match.steps ?? {}) as Record<string, Record<string, unknown>>;
        const discStep = steps.pair_discovery ?? {};
        const discData = (discStep.data ?? {}) as Record<string, unknown>;
        const dr = discData.discovery_result as Record<string, unknown> | undefined;
        if (dr) {
          const ranked = (dr.ranked_pairs ?? dr.all_evaluations ?? []) as Array<Record<string, unknown>>;
          const valid = ranked.filter((p) => String(p.status ?? '').toLowerCase() === 'valid_candidate');
          if (valid.length > 0) {
            // Backend emits win_rate as 0–1 fraction; max_drawdown_pct as 0–1 fraction (negative sign)
            const avgWin = valid.reduce((s, p) => s + Number(p.win_rate ?? 0), 0) / valid.length;
            const avgDD  = valid.reduce((s, p) => s + Math.abs(Number(p.max_drawdown_pct ?? p.max_drawdown ?? 0)), 0) / valid.length;
            const avgPF  = valid.reduce((s, p) => s + Number(p.profit_factor ?? 1), 0) / valid.length;
            // win_rate is a 0–1 fraction from backend; convert to percentage
            const winPct = avgWin <= 1.0 ? avgWin * 100 : avgWin; // guard if already %
            return {
              winRate: Math.round(winPct * 10) / 10,
              maxDrawdown: Math.round(avgDD * 100 * 10) / 10,
              sharpe: Math.round((avgPF - 1) * 10) / 10,
              lossBullets: [
                'Based on pair discovery backtest results',
                valid.length < ranked.length
                  ? `${ranked.length - valid.length} pairs rejected in discovery`
                  : 'All evaluated pairs passed discovery',
              ],
            };
          }
        }
      }
    }
  } catch { /* fall through */ }

  // Fallback: derive from strategy JSON params
  try {
    const filesRes = await fetch(`${API_BASE_URL}/api/strategies/files/${encodeURIComponent(strategyName)}`);
    if (filesRes.ok) {
      const data = await filesRes.json() as Record<string, unknown>;
      const jsonContent = typeof data.json_content === 'string'
        ? JSON.parse(data.json_content) as Record<string, unknown>
        : null;
      const params = (jsonContent?.params ?? {}) as Record<string, unknown>;
      const slObj = params.stoploss as Record<string, unknown> | undefined;
      const sl = Math.abs(Number(slObj?.stoploss ?? -0.10)) * 100;
      return {
        winRate: 0,
        maxDrawdown: sl,
        sharpe: 0,
        lossBullets: [
          'No backtest results available yet — run AeRoing4 to see live metrics',
          `Stoploss configured at -${sl.toFixed(1)}%`,
        ],
      };
    }
  } catch { /* ignore */ }

  return { maxDrawdown: 0, winRate: 0, sharpe: 0, lossBullets: ['Run AeRoing4 to generate metrics for this strategy'] };
}

/** Run a backtest — starts run then polls for completion. */
export async function runBacktest(config: {
  pairs: string[];
  timerange: string;
  stakeAmount: number;
}): Promise<BacktestResult> {
  try {
    // Start the run
    const startRes = await fetch(`${API_BASE_URL}/api/backtest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pairs: config.pairs,
        timerange: config.timerange,
        dry_run_wallet: config.stakeAmount,
      }),
    });
    if (!startRes.ok) throw new Error(`Start failed: ${startRes.status}`);
    const startData = await startRes.json() as Record<string, unknown>;
    const sessionId = String(startData.session_id ?? startData.run_id ?? '');

    // Poll for completion (max 5 minutes)
    if (sessionId) {
      for (let i = 0; i < 150; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const statusRes = await fetch(`${API_BASE_URL}/api/session/status/${sessionId}`);
        if (!statusRes.ok) continue;
        const status = await statusRes.json() as Record<string, unknown>;
        if (status.status === 'completed' && status.run_id) {
          const resultRes = await fetch(`${API_BASE_URL}/api/backtest/results/${status.run_id}`);
          if (resultRes.ok) {
            const result = await resultRes.json() as Record<string, unknown>;
            const summary = (result.summary ?? result) as Record<string, unknown>;
            return {
              totalTrades: Number(summary.total_trades ?? 0),
              winRate: Number(summary.win_rate ?? 0) * 100,
              profitPct: Number(summary.profit_factor ?? 0),
              drawdown: Number(summary.max_drawdown ?? 0) * 100,
              finalEquity: 1000 + Number(summary.profit_closed_usdt ?? 0),
            };
          }
        }
        if (status.status === 'failed') break;
      }
    }
  } catch { /* fall through */ }

  // Return zero-result on failure
  return { totalTrades: 0, winRate: 0, profitPct: 0, drawdown: 0, finalEquity: 1000 };
}

/** Start a legacy pipeline run — returns initial stub state. */
export async function startPipelineRun(pairs: string[]): Promise<PipelineRun> {
  void pairs;
  return {
    id: `run-${Date.now()}`,
    createdAt: new Date().toISOString(),
    status: 'running',
    currentStage: 1,
    stages: _buildStages('pending'),
  };
}

function _buildStages(
  status: 'pending' | 'running' | 'done' | 'error',
  errorAt?: number,
): StageStatus[] {
  const names = [
    'Data Selection',
    'Portfolio Baseline',
    'WFA Hyperopt',
    'Overfit Detection',
    'Stress Test',
    'Risk Assessment',
  ];
  return names.map((name, i) => ({
    id: i + 1,
    name,
    status: errorAt
      ? i + 1 < errorAt
        ? 'done'
        : i + 1 === errorAt
          ? 'error'
          : 'pending'
      : status === 'done'
        ? 'done'
        : status === 'running' && i === 0
          ? 'running'
          : 'pending',
    progress:
      errorAt ? (i + 1 < errorAt ? 100 : 0) : status === 'done' ? 100 : 0,
    logs:
      i === 0 && status !== 'pending'
        ? [
            '[INFO] Loading OHLCV data...',
            '[INFO] 1247 candles loaded for BTC/USDT',
            '[OK] Data validated',
          ]
        : [],
  }));
}

// ── AeRoing4 API ──────────────────────────────────────────────────────────────

/** Start an AeRoing4 run against the real backend. Returns the initial run state. */
export async function startAeRoing4Run(
  req: AeRoing4RunRequest & {
    timeframe?: string;
    smoke_timerange?: string;
    smoke_pairs?: string[];
  },
): Promise<AeRoing4RunState & { _runId: string }> {
  const res = await fetch(`${API_BASE_URL}/api/aeroing4/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      strategy_name: req.strategy_name,
      timeframe: req.timeframe ?? '5m',
      smoke_timerange: req.smoke_timerange ?? '20240101-20240131',
      smoke_pairs: req.smoke_pairs ?? ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'],
      enable_pair_discovery: req.enable_pair_discovery ?? true,
      discovery_pairs: req.discovery_pairs ?? null,
      discovery_timerange: req.discovery_timerange ?? null,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText })) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }

  const data = await res.json() as Record<string, unknown>;
  const runId = String(data.run_id ?? '');

  return {
    _runId: runId,
    id: runId,
    created_at: new Date().toISOString(),
    strategy_name: req.strategy_name,
    strategy_timeframe: req.timeframe ?? '5m',
    discovery_pairs: req.discovery_pairs ?? DEFAULT_DISCOVERY_UNIVERSE,
    discovery_timerange: req.discovery_timerange ?? '',
    smoke_timerange: req.smoke_timerange ?? '20240101-20240131',
    enable_pair_discovery: req.enable_pair_discovery ?? true,
    status: 'running',
    outcome: 'IN_PROGRESS',
    smoke_outcome: null,
    steps: [
      { id: 'validation',       name: 'Strategy Validation', status: 'pending', progress: 0, logs: [] },
      { id: 'data_preparation', name: 'Smoke Data Prep',      status: 'pending', progress: 0, logs: [] },
      { id: 'smoke_backtest',   name: 'Smoke Backtest',       status: 'pending', progress: 0, logs: [] },
      { id: 'pair_discovery',   name: 'Pair Discovery',       status: 'pending', progress: 0, logs: [] },
    ],
    discovery_result: null,
  };
}

/** Poll backend for a run's current state. */
export async function getAeRoing4Run(runId: string): Promise<AeRoing4RunState> {
  const res = await fetch(`${API_BASE_URL}/api/aeroing4/runs/${runId}`);
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
  const data = await res.json() as Record<string, unknown>;
  return mapBackendRun(data);
}

export async function getStrategyLibraryScan(): Promise<StrategyLibraryScan> {
  const res = await fetch(`${API_BASE_URL}/api/aeroing4/strategy-library`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Strategy library scan failed: ${res.status}`);
  return await res.json() as StrategyLibraryScan;
}

export async function getLatestAutoQuantFlow(): Promise<AutoQuantFlowResponse> {
  const res = await fetch(`${API_BASE_URL}/api/aeroing4/candidate-flow/latest`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Candidate flow load failed: ${res.status}`);
  return await res.json() as AutoQuantFlowResponse;
}

export async function getAutoQuantFlowForRun(runId: string): Promise<AutoQuantFlowResponse> {
  const res = await fetch(`${API_BASE_URL}/api/aeroing4/runs/${runId}/candidate-flow`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Candidate flow load failed: ${res.status}`);
  return await res.json() as AutoQuantFlowResponse;
}

// ── Backend Settings API ───────────────────────────────────────────────────────

export interface BackendSettings {
  freqtrade_executable_path: string;
  strategies_directory_path: string;
  user_data_directory_path: string;
  default_config_file_path: string;
  ollama_api_url: string;
  ollama_model: string;
  ollama_provider: string;
  ollama_api_key: string;
  ollama_temperature: number;
  network_mode: string;
  hyperopt_workers: number;
  ollama_self_healing_enabled: boolean;
  ollama_timeout: number;
  ollama_retry_delays: number[];
  ollama_circuit_breaker_threshold: number;
  ollama_circuit_breaker_cooldown: number;
  ollama_enable_health_check: boolean;
  ollama_health_check_interval: number;
  ollama_timeout_chat: number;
  ollama_timeout_generate: number;
  ollama_timeout_autoquant: number;
  ollama_connection_pool_size: number;
  ollama_connection_keepalive: number;
  ollama_model_chat: string;
  ollama_model_autoquant: string;
  ollama_model_strategylab: string;
  ollama_model_optimizer: string;
  ai_assistant_sandbox_enabled: boolean;
  // Research data zones
  research_development_start: string;
  research_development_end: string;
  research_confirmation_start: string;
  research_confirmation_end: string;
  research_unseen_start: string;
  // Research pipeline defaults
  research_max_open_trades: number;
  research_pair_universe_size: number;
  research_smoke_pairs: string[];
  discord_enabled?: boolean;
  discord_bot_token?: string;
  discord_server_id?: string;
  discord_user_id?: string;
  discord_notification_channel_id?: string | null;
}

export interface BackendHealth {
  ok: boolean;
  services?: string[];
  message?: string;
}

/** Load the active backend settings from the FastAPI settings store. */
export async function getBackendSettings(): Promise<BackendSettings | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/settings`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json() as { settings: BackendSettings };
    return data.settings ?? null;
  } catch {
    return null;
  }
}

/** Persist a full settings payload to the backend settings store. */
export async function saveBackendSettings(
  settings: BackendSettings,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText })) as { detail?: string };
      return { ok: false, error: err.detail ?? `HTTP ${res.status}` };
    }
    return { ok: true };
  } catch (exc) {
    return { ok: false, error: exc instanceof Error ? exc.message : 'Network error' };
  }
}

/** Ping the backend health endpoint. */
export async function checkBackendHealth(): Promise<BackendHealth> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json() as BackendHealth;
    return { ok: true, services: data.services, message: data.message ?? 'ok' };
  } catch (exc) {
    return { ok: false, message: exc instanceof Error ? exc.message : 'offline' };
  }
}
