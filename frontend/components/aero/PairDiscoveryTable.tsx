"use client";
import { useState } from "react";
import { ChevronDown, ChevronUp, ChevronRight } from "lucide-react";
import type { DiscoveryPairResult, PairStatus } from "@/lib/api";
import { RankScoreMeter } from "./RankScoreMeter";

type SortKey = "rank" | "score" | "trades" | "profit" | "pf" | "dd" | "wr";

interface Props { pairs: DiscoveryPairResult[] }

const STATUS_CFG: Record<PairStatus, { label: string; bg: string; border: string; color: string }> = {
  VALID_CANDIDATE:   { label: "VALID",        bg: "rgba(0,255,136,0.08)",  border: "rgba(0,255,136,0.3)",  color: "#00FF88" },
  ZERO_TRADES:       { label: "ZERO TRADES",  bg: "rgba(255,59,92,0.08)",  border: "rgba(255,59,92,0.3)",  color: "#FF3B5C" },
  INSUFFICIENT_TRADES:{ label: "INSUFF.",     bg: "rgba(255,184,0,0.08)",  border: "rgba(255,184,0,0.3)",  color: "#FFB800" },
  DATA_UNAVAILABLE:  { label: "NO DATA",      bg: "rgba(100,100,100,0.08)",border: "rgba(100,100,100,0.3)",color: "#555555" },
  EXECUTION_FAILURE: { label: "EXEC FAIL",    bg: "rgba(255,59,92,0.08)",  border: "rgba(255,59,92,0.3)",  color: "#FF3B5C" },
};

const COLS: { key: SortKey; label: string }[] = [
  { key: "rank",   label: "RANK"   },
  { key: "score",  label: "SCORE"  },
  { key: "trades", label: "TRADES" },
  { key: "profit", label: "PROFIT" },
  { key: "pf",     label: "PF"     },
  { key: "dd",     label: "MAX DD" },
  { key: "wr",     label: "WIN %"  },
];

export function PairDiscoveryTable({ pairs }: Props) {
  const [sortKey, setSortKey]   = useState<SortKey>("rank");
  const [sortAsc, setSortAsc]   = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const sorted = [...pairs].sort((a, b) => {
    let va = 0, vb = 0;
    if (sortKey === "rank")   { va = a.rank   ?? 9999; vb = b.rank   ?? 9999; }
    if (sortKey === "score")  { va = a.rank_score    ?? -1;   vb = b.rank_score    ?? -1; }
    if (sortKey === "trades") { va = a.total_trades  ?? -1;   vb = b.total_trades  ?? -1; }
    if (sortKey === "profit") { va = a.net_profit_pct ?? -999; vb = b.net_profit_pct ?? -999; }
    if (sortKey === "pf")     { va = a.profit_factor ?? -1;  vb = b.profit_factor ?? -1; }
    if (sortKey === "dd")     { va = a.max_drawdown  ?? 999; vb = b.max_drawdown  ?? 999; }
    if (sortKey === "wr")     { va = a.win_rate      ?? -1;  vb = b.win_rate      ?? -1; }
    return sortAsc ? va - vb : vb - va;
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(a => !a);
    else { setSortKey(key); setSortAsc(true); }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono border-collapse">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--t-border)" }}>
            <th className="text-left px-2 py-2" style={{ color: "var(--t-muted)", minWidth: 120 }}>PAIR</th>
            <th className="px-2 py-2 text-left" style={{ color: "var(--t-muted)", minWidth: 80 }}>STATUS</th>
            {COLS.map(c => (
              <th key={c.key} className="px-2 py-2 text-right cursor-pointer select-none"
                style={{ color: sortKey === c.key ? "var(--t-cyan)" : "var(--t-muted)" }}
                onClick={() => handleSort(c.key)}>
                <span className="flex items-center justify-end gap-1">
                  {c.label}
                  {sortKey === c.key
                    ? sortAsc ? <ChevronUp size={9}/> : <ChevronDown size={9}/>
                    : <ChevronRight size={9} style={{ opacity: 0.3 }}/>}
                </span>
              </th>
            ))}
            <th className="px-2 py-2 w-6" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const cfg = STATUS_CFG[row.status];
            const win = row.status === "VALID_CANDIDATE";
            const hasDetail = row.rejection_reasons.length > 0 || row.score_inputs !== null;
            return (
              <>
                <tr key={row.pair}
                  className="trade-row"
                  style={{
                    borderBottom: "1px solid rgba(255,255,255,0.03)",
                    background: win ? "rgba(0,255,136,0.02)" : "rgba(255,255,255,0.01)",
                    borderLeft: win ? "2px solid rgba(0,255,136,0.25)" : "2px solid rgba(255,255,255,0.05)",
                    animationDelay: `${i * 35}ms`,
                  }}>
                  {/* Pair */}
                  <td className="px-2 py-2 font-semibold" style={{ color: "var(--t-text)" }}>{row.pair}</td>
                  {/* Status badge */}
                  <td className="px-2 py-2">
                    <span className="px-1.5 py-0.5 text-[9px] font-bold"
                      style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, color: cfg.color }}>
                      {cfg.label}
                    </span>
                  </td>
                  {/* Rank */}
                  <td className="px-2 py-2 text-right">
                    {row.rank !== null
                      ? <span className="font-bold" style={{ color: row.rank <= 3 ? "var(--t-cyan)" : "var(--t-text)" }}>#{row.rank}</span>
                      : <span style={{ color: "var(--t-muted)" }}>—</span>}
                  </td>
                  {/* Score meter */}
                  <td className="px-2 py-2">
                    {row.rank_score !== null
                      ? <div className="flex items-center gap-1.5 justify-end">
                          <span className="font-bold" style={{ color: "var(--t-text)" }}>{row.rank_score.toFixed(1)}</span>
                          <RankScoreMeter score={row.rank_score} width={48} height={5} />
                        </div>
                      : <span style={{ color: "var(--t-muted)" }}>—</span>}
                  </td>
                  {/* Trades */}
                  <td className="px-2 py-2 text-right" style={{ color: row.total_trades !== null ? "var(--t-text)" : "var(--t-muted)" }}>
                    {row.total_trades ?? "—"}
                  </td>
                  {/* Profit */}
                  <td className="px-2 py-2 text-right font-bold"
                    style={{ color: row.net_profit_pct === null ? "var(--t-muted)" : row.net_profit_pct >= 0 ? "var(--t-green)" : "var(--t-red)" }}>
                    {row.net_profit_pct !== null ? `${row.net_profit_pct >= 0 ? "+" : ""}${row.net_profit_pct.toFixed(2)}%` : "—"}
                  </td>
                  {/* Profit factor */}
                  <td className="px-2 py-2 text-right" style={{ color: row.profit_factor !== null ? "var(--t-text)" : "var(--t-muted)" }}>
                    {row.profit_factor?.toFixed(3) ?? "—"}
                  </td>
                  {/* Drawdown */}
                  <td className="px-2 py-2 text-right" style={{ color: row.max_drawdown !== null ? "var(--t-red)" : "var(--t-muted)" }}>
                    {row.max_drawdown !== null ? `${(row.max_drawdown * 100).toFixed(1)}%` : "—"}
                  </td>
                  {/* Win rate */}
                  <td className="px-2 py-2 text-right" style={{ color: row.win_rate !== null ? "var(--t-text)" : "var(--t-muted)" }}>
                    {row.win_rate !== null ? `${row.win_rate.toFixed(1)}%` : "—"}
                  </td>
                  {/* Expand */}
                  <td className="px-2 py-2">
                    {hasDetail && (
                      <button onClick={() => setExpanded(expanded === row.pair ? null : row.pair)}
                        style={{ color: "var(--t-muted)" }}>
                        {expanded === row.pair ? <ChevronDown size={11}/> : <ChevronRight size={11}/>}
                      </button>
                    )}
                  </td>
                </tr>
                {expanded === row.pair && (
                  <tr key={`${row.pair}-detail`} style={{ background: "#080808" }}>
                    <td colSpan={10} className="px-4 py-3">
                      <DetailPanel row={row} />
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DetailPanel({ row }: { row: DiscoveryPairResult }) {
  return (
    <div className="space-y-2 text-[11px] font-mono">
      {row.rejection_reasons.length > 0 && (
        <div>
          <span className="t-label block mb-1">REJECTION REASONS</span>
          {row.rejection_reasons.map((r, i) => (
            <div key={i} style={{ color: "var(--t-red)" }}>› {r}</div>
          ))}
        </div>
      )}
      {row.score_inputs && (
        <div>
          <span className="t-label block mb-1">SCORE BREAKDOWN · aero-discovery-v1</span>
          <div className="grid grid-cols-5 gap-x-4 gap-y-1">
            {([
              ["Trade Sufficiency", row.score_inputs.trade_sufficiency_score, 30],
              ["Expectancy",        row.score_inputs.expectancy_score,        25],
              ["Profit Factor",     row.score_inputs.profit_factor_score,     25],
              ["Drawdown Penalty",  row.score_inputs.drawdown_penalty,        10],
              ["Net Profit",        row.score_inputs.net_profit_score,        10],
            ] as [string, number | null, number][]).map(([label, val, max]) => (
              <div key={label}>
                <span style={{ color: "var(--t-muted)" }}>{label}</span>
                <div className="flex items-center gap-1 mt-0.5">
                  <span style={{ color: "var(--t-cyan)" }}>{val?.toFixed(1) ?? "—"}</span>
                  <span style={{ color: "var(--t-muted)" }}>/{max}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      <div style={{ color: "var(--t-muted)" }}>
        run_id: {row.backtest_run_id}
        {row.average_trade_duration && <span className="ml-4">avg duration: {row.average_trade_duration}</span>}
        {row.expectancy !== null && <span className="ml-4">expectancy: {row.expectancy.toFixed(5)}</span>}
      </div>
    </div>
  );
}
