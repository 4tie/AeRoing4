"""HTML report generation for Auto-Quant."""

from typing import Any


def _fmt(val: Any, decimals: int = 2, suffix: str = "") -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def _val_class(ok: bool | None) -> str:
    if ok is True:
        return "pass-val"
    if ok is False:
        return "fail-val"
    return "neutral-val"


def _build_html_report(report: dict[str, Any], wfo_windows: list) -> str:
    run_id    = report.get("run_id", "\u2014")
    strategy  = report.get("strategy", "\u2014")
    opt_strat = report.get("optimized_strategy", "\u2014")
    status    = report.get("status", "\u2014")
    created   = report.get("created_at") or report.get("started_at") or "\u2014"
    completed = report.get("completed_at") or "\u2014"

    stages     = report.get("stages") or []
    oos        = report.get("oos_validation") or {}
    risk       = report.get("risk") or {}
    mc         = report.get("monte_carlo") or risk.get("monte_carlo") or {}
    stress     = report.get("stress_test") or {}
    thresholds = report.get("thresholds") or {}
    sanity     = report.get("sanity_backtest") or {}

    max_dd_thr = thresholds.get("max_drawdown", 30)
    min_wr_thr = thresholds.get("min_win_rate", 40)
    min_pf_thr = thresholds.get("min_profit_factor", 1.0)
    min_sh_thr = thresholds.get("min_sharpe", 0.5)
    mc_thr     = thresholds.get("monte_carlo_threshold", 0.35)
    min_oos_pr = thresholds.get("min_oos_profit", 0)

    NA = "\u2014"  # em dash used as a "no data" placeholder

    # ── Stages table ──────────────────────────────────────────────────────────
    stage_rows = ""
    for s in stages:
        st = s.get("status", "pending")
        color = {"passed": "#22c55e", "failed": "#ef4444", "running": "#f59e0b",
                 "pending": "#94a3b8"}.get(st, "#94a3b8")
        icon = {"passed": "\u2714", "failed": "\u2718", "running": "\u25b6",
                "pending": "\u25cb"}.get(st, "\u25cb")
        s_msg = s.get("message") or NA
        s_idx = s.get("index", "")
        s_name = s.get("name", "")
        stage_rows += (
            "<tr>"
            + f"<td>{s_idx}</td>"
            + f"<td>{s_name}</td>"
            + f'<td style="color:{color};font-weight:600">{icon} {st.capitalize()}</td>'
            + f"<td>{s_msg}</td>"
            + "</tr>\n"
        )
    if not stage_rows:
        stage_rows = "<tr><td colspan='4' style='color:#64748b'>No stage data</td></tr>"

    # ── Risk checks ───────────────────────────────────────────────────────────
    checks = risk.get("checks") or []
    check_rows = ""
    for c in checks:
        ok       = c.get("passed")
        color    = "#22c55e" if ok else "#ef4444"
        icon     = "\u2714" if ok else "\u2718"
        c_val    = c.get("value")
        c_val_s  = str(c_val) if c_val is not None else NA
        c_name   = c.get("name") or NA
        c_thr    = c.get("threshold") or NA
        c_msg    = c.get("message") or NA
        check_rows += (
            "<tr>"
            + f"<td>{c_name}</td>"
            + f'<td style="color:{color}">{icon}</td>'
            + f"<td>{c_val_s}</td>"
            + f"<td>{c_thr}</td>"
            + f"<td>{c_msg}</td>"
            + "</tr>\n"
        )

    check_table = ""
    if check_rows:
        check_table = (
            '<div class="table-wrap"><table>'
            "<thead><tr><th>Check</th><th>Result</th><th>Value</th>"
            "<th>Threshold</th><th>Notes</th></tr></thead>"
            f"<tbody>{check_rows}</tbody></table></div>"
        )

    # ── Stress test pairs ─────────────────────────────────────────────────────
    passing = stress.get("passing_pairs") or []
    failing = stress.get("failing_pairs") or []

    def pair_spans(pairs: list, css_class: str) -> str:
        if not pairs:
            return '<span style="color:#94a3b8">none</span>'
        return " ".join(
            f'<span class="pair {css_class}">{p}</span>' for p in pairs
        )

    stress_section = ""
    if passing or failing:
        stress_section = (
            "<section>"
            "<h2>Stress Test Pairs</h2>"
            '<div style="margin-bottom:10px">'
            f'<div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">Passing ({len(passing)})</div>'
            f"<div>{pair_spans(passing, 'pass')}</div>"
            "</div><div>"
            f'<div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">Failing ({len(failing)})</div>'
            f"<div>{pair_spans(failing, 'fail')}</div>"
            "</div></section>"
        )

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    mc_p95    = mc.get("p95_drawdown")
    mc_p5     = mc.get("p5_drawdown")
    mc_median = mc.get("median_final_return")
    mc_passed = mc.get("passed")

    mc_section = ""
    if mc:
        mc_p95_val    = _fmt(mc_p95 * 100 if mc_p95 is not None else None, 1, "%")
        mc_p5_val     = _fmt(mc_p5 * 100 if mc_p5 is not None else None, 1, "%")
        mc_med_val    = _fmt(mc_median * 100 if mc_median is not None else None, 2, "%")
        mc_verdict    = ("PASS" if mc_passed else "FAIL") if mc_passed is not None else "\u2014"
        mc_p95_cls    = _val_class(mc_passed)
        mc_verd_cls   = _val_class(mc_passed)
        mc_thr_pct    = f"{mc_thr * 100:.1f}"
        mc_section = (
            "<section><h2>Monte Carlo Stress Test</h2>"
            '<div class="metrics-grid">'
            f'<div class="metric-card"><div class="label">p95 Drawdown</div>'
            f'<div class="value {mc_p95_cls}">{mc_p95_val}</div>'
            f"<div class=\"threshold\">&lt; {mc_thr_pct}%</div></div>"
            f'<div class="metric-card"><div class="label">p5 Drawdown</div>'
            f'<div class="value neutral-val">{mc_p5_val}</div></div>'
            f'<div class="metric-card"><div class="label">Median Return</div>'
            f'<div class="value neutral-val">{mc_med_val}</div></div>'
            f'<div class="metric-card"><div class="label">Verdict</div>'
            f'<div class="value {mc_verd_cls}">{mc_verdict}</div></div>'
            "</div></section>"
        )

    # ── WFO table ─────────────────────────────────────────────────────────────
    wfo_section = ""
    if wfo_windows:
        wfo_rows = ""
        for w in wfo_windows:
            profit     = w.get("profit")
            st         = w.get("status") or NA
            color      = {"passed": "#22c55e", "warning": "#f59e0b",
                          "failed": "#ef4444"}.get(st, "#94a3b8")
            profit_str = _fmt(profit, 2, "%") if profit is not None else NA
            w_win      = w.get("window", "?")
            w_is       = w.get("is_range") or NA
            w_oos      = w.get("oos_range") or NA
            w_dd       = _fmt(w.get("max_dd"), 2, "%")
            w_trades   = str(w.get("trades")) if w.get("trades") is not None else NA
            w_rw       = _fmt(w.get("recency_weight"), 3)
            w_wp       = _fmt(w.get("weighted_profit"), 2, "%")
            wfo_rows += (
                "<tr>"
                + f"<td>W{w_win}</td>"
                + f"<td>{w_is}</td>"
                + f"<td>{w_oos}</td>"
                + f"<td>{profit_str}</td>"
                + f"<td>{w_dd}</td>"
                + f"<td>{w_trades}</td>"
                + f"<td>{w_rw}</td>"
                + f"<td>{w_wp}</td>"
                + f'<td style="color:{color};font-weight:600">{st.capitalize()}</td>'
                + "</tr>\n"
            )
        wfo_section = (
            "<section><h2>Walk-Forward Optimization Windows</h2>"
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Window</th><th>IS Range</th><th>OOS Range</th>"
            "<th>OOS Profit</th><th>Max DD</th><th>Trades</th>"
            "<th>Recency W</th><th>Weighted Profit</th><th>Status</th>"
            f"</tr></thead><tbody>{wfo_rows}</tbody></table></div></section>"
        )

    # ── OOS metrics ───────────────────────────────────────────────────────────
    oos_profit    = oos.get("profit_total")
    oos_profit_ok = oos_profit is not None and oos_profit >= min_oos_pr
    oos_max_dd    = oos.get("max_drawdown_account")
    oos_trades    = oos.get("total_trades") or "\u2014"

    oos_profit_str = _fmt(oos_profit * 100 if oos_profit is not None else None, 2, "%")
    oos_dd_str     = _fmt(oos_max_dd * 100 if oos_max_dd is not None else None, 2, "%")
    is_profit_str  = _fmt(sanity.get("profit_total_abs"), 2, " USDT")
    oos_profit_cls = _val_class(oos_profit_ok if oos_profit is not None else None)

    # ── Risk metrics ──────────────────────────────────────────────────────────
    risk_max_dd = risk.get("max_drawdown_pct")
    risk_wr     = risk.get("win_rate_pct")
    risk_pf     = risk.get("profit_factor")
    risk_sharpe = risk.get("sharpe_ratio")

    dd_ok = risk_max_dd is not None and risk_max_dd < max_dd_thr
    wr_ok = risk_wr is not None and risk_wr >= min_wr_thr
    pf_ok = risk_pf is not None and risk_pf >= min_pf_thr
    sh_ok = risk_sharpe is not None and risk_sharpe >= min_sh_thr

    dd_val  = _fmt(risk_max_dd, 1, "%")
    wr_val  = _fmt(risk_wr, 1, "%")
    pf_val  = _fmt(risk_pf, 2)
    sh_val  = _fmt(risk_sharpe, 2)
    mc_pct  = f"{mc_thr * 100:.1f}"

    # ── Assemble HTML ─────────────────────────────────────────────────────────
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>Auto-Quant Report \u2014 {run_id}</title>",
        "<style>",
        "  *, *::before, *::after { box-sizing: border-box; }",
        "  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"
        " font-size: 14px; color: #e2e8f0; background: #0f172a;"
        " margin: 0; padding: 24px; line-height: 1.6; }",
        "  h1 { font-size: 1.4rem; font-weight: 700; color: #f8fafc; margin: 0 0 4px 0; }",
        "  h2 { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;"
        " text-transform: uppercase; color: #94a3b8; margin: 0 0 10px 0;"
        " padding-bottom: 6px; border-bottom: 1px solid #1e293b; }",
        "  .subtitle { color: #94a3b8; font-size: 0.82rem; margin: 0 0 28px 0; }",
        "  section { margin-bottom: 28px; }",
        "  .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));"
        " gap: 10px; margin-bottom: 28px; }",
        "  .meta-card { background: #1e293b; border-radius: 8px; padding: 12px 14px;"
        " border: 1px solid #334155; }",
        "  .meta-card .label { font-size: 0.7rem; color: #64748b; text-transform: uppercase;"
        " letter-spacing: 0.06em; margin-bottom: 3px; }",
        "  .meta-card .value { font-size: 0.9rem; font-weight: 600; color: #f1f5f9;"
        " word-break: break-all; }",
        "  .metrics-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));"
        " gap: 10px; margin-bottom: 16px; }",
        "  .metric-card { background: #1e293b; border-radius: 8px; padding: 12px 14px;"
        " border: 1px solid #334155; }",
        "  .metric-card .label { font-size: 0.68rem; color: #64748b; text-transform: uppercase;"
        " letter-spacing: 0.06em; margin-bottom: 3px; }",
        "  .metric-card .value { font-size: 1.1rem; font-weight: 700; }",
        "  .metric-card .threshold { font-size: 0.68rem; color: #64748b; margin-top: 2px; }",
        "  .pass-val { color: #22c55e; }",
        "  .fail-val { color: #ef4444; }",
        "  .neutral-val { color: #e2e8f0; }",
        "  .table-wrap { overflow-x: auto; }",
        "  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }",
        "  thead th { background: #1e293b; color: #94a3b8; font-weight: 600; font-size: 0.7rem;"
        " text-transform: uppercase; letter-spacing: 0.06em;"
        " padding: 8px 10px; text-align: left; border-bottom: 1px solid #334155; }",
        "  tbody tr { border-bottom: 1px solid #1e293b; }",
        "  tbody tr:last-child { border-bottom: none; }",
        "  tbody td { padding: 7px 10px; color: #cbd5e1; vertical-align: top; }",
        "  tbody tr:hover td { background: #1e293b; }",
        "  .pair { display: inline-block; padding: 1px 7px; border-radius: 6px;"
        " font-size: 0.72rem; font-weight: 600; margin: 2px; }",
        "  .pair.pass { background: #14532d; color: #22c55e; }",
        "  .pair.fail { background: #450a0a; color: #ef4444; }",
        "  .thr-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; }",
        "  .thr-pill { background: #1e293b; border: 1px solid #334155; border-radius: 9999px;"
        " padding: 2px 10px; font-size: 0.7rem; color: #94a3b8; }",
        "  .report-footer { margin-top: 36px; padding-top: 12px; border-top: 1px solid #1e293b;"
        " font-size: 0.72rem; color: #475569; text-align: right; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Auto-Quant Factory Report</h1>",
        f'<p class="subtitle">Run ID: {run_id}</p>',
        '<div class="meta-grid">',
        f'  <div class="meta-card"><div class="label">Strategy</div><div class="value">{strategy}</div></div>',
        f'  <div class="meta-card"><div class="label">Optimized Strategy</div><div class="value">{opt_strat}</div></div>',
        f'  <div class="meta-card"><div class="label">Status</div><div class="value">{status.upper()}</div></div>',
        f'  <div class="meta-card"><div class="label">Started</div><div class="value">{created}</div></div>',
        f'  <div class="meta-card"><div class="label">Completed</div><div class="value">{completed}</div></div>',
        "</div>",
        '<div class="thr-list">',
        f'  <span class="thr-pill">DD &lt; {max_dd_thr}%</span>',
        f'  <span class="thr-pill">Win \u2265 {min_wr_thr}%</span>',
        f'  <span class="thr-pill">PF \u2265 {min_pf_thr}</span>',
        f'  <span class="thr-pill">Sharpe \u2265 {min_sh_thr}</span>',
        f'  <span class="thr-pill">MC p95 &lt; {mc_pct}%</span>',
        "</div>",
        "<section><h2>Pipeline Stages</h2>",
        '<div class="table-wrap"><table>',
        "<thead><tr><th>#</th><th>Stage</th><th>Status</th><th>Message</th></tr></thead>",
        f"<tbody>{stage_rows}</tbody></table></div></section>",
        "<section><h2>OOS Metrics</h2>",
        '<div class="metrics-grid">',
        f'  <div class="metric-card"><div class="label">OOS Profit</div>'
        f'  <div class="value {oos_profit_cls}">{oos_profit_str}</div>'
        f'  <div class="threshold">\u2265 {min_oos_pr}%</div></div>',
        f'  <div class="metric-card"><div class="label">OOS Max Drawdown</div>'
        f'  <div class="value neutral-val">{oos_dd_str}</div></div>',
        f'  <div class="metric-card"><div class="label">In-Sample Profit</div>'
        f'  <div class="value neutral-val">{is_profit_str}</div></div>',
        f'  <div class="metric-card"><div class="label">OOS Total Trades</div>'
        f'  <div class="value neutral-val">{oos_trades}</div></div>',
        "</div></section>",
        "<section><h2>Risk Assessment</h2>",
        '<div class="metrics-grid">',
        f'  <div class="metric-card"><div class="label">Max Drawdown</div>'
        f'  <div class="value {_val_class(dd_ok if risk_max_dd is not None else None)}">{dd_val}</div>'
        f'  <div class="threshold">&lt; {max_dd_thr}%</div></div>',
        f'  <div class="metric-card"><div class="label">Win Rate</div>'
        f'  <div class="value {_val_class(wr_ok if risk_wr is not None else None)}">{wr_val}</div>'
        f'  <div class="threshold">\u2265 {min_wr_thr}%</div></div>',
        f'  <div class="metric-card"><div class="label">Profit Factor</div>'
        f'  <div class="value {_val_class(pf_ok if risk_pf is not None else None)}">{pf_val}</div>'
        f'  <div class="threshold">\u2265 {min_pf_thr}</div></div>',
        f'  <div class="metric-card"><div class="label">Sharpe Ratio</div>'
        f'  <div class="value {_val_class(sh_ok if risk_sharpe is not None else None)}">{sh_val}</div>'
        f'  <div class="threshold">\u2265 {min_sh_thr}</div></div>',
        "</div>",
        check_table,
        "</section>",
        mc_section,
        stress_section,
        wfo_section,
        f'<div class="report-footer">Generated by Strategy Lab &mdash; {run_id}</div>',
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)
