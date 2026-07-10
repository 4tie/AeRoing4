"""Performance tab API helper services."""

from __future__ import annotations

from typing import Any

from ...models import ParsedSummary
from ...utils import read_json


def summary_row(metadata, parsed_summary) -> dict[str, Any]:
    """Flatten RunMetadata and ParsedSummary into the Performance table row shape."""
    row: dict[str, Any] = {
        "run_id": metadata.run_id,
        "strategy_name": metadata.strategy_name,
        "strategy_version_id": metadata.strategy_version_id,
        "timeframe": metadata.timeframe,
        "pairs": metadata.pairs,
        "timerange": metadata.timerange,
        "run_status": (
            metadata.run_status.value
            if hasattr(metadata.run_status, "value")
            else str(metadata.run_status)
        ),
        "created_at": metadata.created_at.isoformat(),
        "completed_at": metadata.completed_at.isoformat() if metadata.completed_at else None,
        "net_profit_pct": None,
        "max_drawdown_pct": None,
        "total_trades": None,
        "win_rate_pct": None,
        "sharpe_ratio": None,
        "profit_factor": None,
    }
    if parsed_summary:
        row["net_profit_pct"] = parsed_summary.net_profit_pct
        row["max_drawdown_pct"] = parsed_summary.max_drawdown_pct
        row["total_trades"] = parsed_summary.total_trades
        row["win_rate_pct"] = parsed_summary.win_rate_pct
        row["sharpe_ratio"] = parsed_summary.sharpe_ratio
        row["profit_factor"] = parsed_summary.profit_factor
    return row


def load_parsed_summary(run_repository, run_id: str) -> ParsedSummary | None:
    """Best-effort load of parsed_summary.json for a run."""
    try:
        run_dir = run_repository.find_run_dir(run_id)
        summary_path = run_dir / "parsed_summary.json"
        if summary_path.exists():
            raw = read_json(summary_path)
            if raw:
                return ParsedSummary.model_validate(raw)
    except Exception:
        pass
    return None


def run_detail_payload(detail, params_snapshot: dict | None) -> dict:
    """Convert RunDetail into the existing Performance detail response shape."""
    return {
        "run_id": detail.metadata.run_id,
        "metadata": detail.metadata.model_dump(mode="json"),
        "parsed_summary": (
            detail.parsed_summary.model_dump(mode="json")
            if detail.parsed_summary
            else None
        ),
        "pair_results": [pair.model_dump(mode="json") for pair in detail.pair_results],
        "advanced_metrics": (
            detail.advanced_metrics.model_dump(mode="json")
            if detail.advanced_metrics
            else None
        ),
        "trades_count": len(detail.trades),
        "params_snapshot": params_snapshot,
        "freqtrade_command": detail.freqtrade_command,
    }
