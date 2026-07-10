"""Pair decision logic for deciding final approved pair set from individual + portfolio results."""


def decide_final_pair_set(
    individual_results: list[dict],
    portfolio_result: dict,
    risk_profile: str = "balanced",
    min_approved_pairs: int = 3,
    max_approved_pairs: int = 5,
) -> dict:
    """Decide the final approved pair set from individual + portfolio results.

    Pure rule-based decision helper. No AI, no side effects, no backtests.
    """
    valid_profiles = {"low", "balanced", "aggressive"}
    if risk_profile not in valid_profiles:
        risk_profile = "balanced"

    empty_result = {
        "verdict": "rejected",
        "approved_pairs": [],
        "approved_count": 0,
        "min_approved_pairs": min_approved_pairs,
        "max_approved_pairs": max_approved_pairs,
        "risk_profile": risk_profile,
        "rejection_reason": None,
        "combined_scores": [],
        "portfolio_verdict": portfolio_result.get("status", "unknown"),
        "portfolio_failure_reasons": portfolio_result.get("failure_reasons", []),
    }

    # Quick reject: portfolio backtest failed to execute
    if portfolio_result.get("status") == "backtest_failed":
        return {**empty_result, "rejection_reason": "Portfolio backtest failed to execute"}

    # Portfolio-level override: specific failures reject the whole set
    portfolio_failures = set(portfolio_result.get("failure_reasons", []))
    if portfolio_result.get("status") == "failed" and (
        "MIN_PROFIT_FACTOR" in portfolio_failures or "MAX_DRAWDOWN" in portfolio_failures
    ):
        return {**empty_result, "rejection_reason": "Portfolio backtest failed critical thresholds"}

    # Filter individual results to passed only
    passed = [r for r in individual_results if r.get("status") == "passed"]
    if not passed:
        return {**empty_result, "rejection_reason": "No individual pairs passed screening"}

    # Build portfolio lookup by pair
    portfolio_lookup: dict[str, dict] = {}
    for ppm in portfolio_result.get("per_pair_metrics", []):
        pair_name = ppm.get("pair", "")
        if pair_name:
            portfolio_lookup[pair_name] = ppm

    # Define risk-profile filter rules
    def _risk_filter_rule(ind: dict) -> bool:
        dd = ind.get("max_drawdown")
        safe_dd = dd if dd is not None else float("inf")
        ind_trades = ind.get("total_trades", 0) or 0
        pair = ind.get("pair", "")
        port_data = portfolio_lookup.get(pair, {})

        if risk_profile == "low":
            if safe_dd >= 15:
                return False
            port_trades = port_data.get("trades", 0) or 0
            port_profit = port_data.get("profit_factor")
            if port_trades == 0:
                return False
            if port_profit is not None and port_profit <= 0:
                return False
            return True

        if risk_profile == "aggressive":
            if safe_dd >= 35:
                return False
            if ind_trades == 0:
                return False
            return True

        # balanced (default)
        if safe_dd >= 25:
            return False
        port_trades = port_data.get("trades", 0) or 0
        port_profit = port_data.get("profit_factor")
        if port_trades == 0 and (port_profit is not None and port_profit < 0):
            return False
        return True

    def _portfolio_penalty(ind: dict) -> float:
        pair = ind.get("pair", "")
        port_data = portfolio_lookup.get(pair, {})
        if not port_data:
            return 0.8
        port_trades = port_data.get("trades", 0) or 0
        port_profit = port_data.get("profit_factor")
        if port_trades > 0 and port_profit is not None and port_profit > 0:
            return 1.0
        if port_trades > 0 and port_profit is not None and port_profit <= 0:
            return 0.5
        if port_trades == 0:
            return 0.3
        return 0.8

    combined_scores: list[dict] = []
    for ind in passed:
        indiv_score = ind.get("score", 0.0) or 0.0
        penalty = _portfolio_penalty(ind)
        combined = indiv_score * penalty
        dd = ind.get("max_drawdown")
        pair = ind.get("pair", "")
        port_data = portfolio_lookup.get(pair, {})
        survived = _risk_filter_rule(ind)

        combined_scores.append({
            "pair": pair,
            "individual_score": round(indiv_score, 6),
            "portfolio_penalty": penalty,
            "combined_score": round(combined, 6),
            "individual_max_drawdown": dd,
            "portfolio_trades": port_data.get("trades") if port_data else None,
            "portfolio_profit_factor": port_data.get("profit_factor") if port_data else None,
            "survived_risk_filter": survived,
        })

    # Filter survivors and rank by combined score descending
    survivors = [s for s in combined_scores if s["survived_risk_filter"]]
    survivors.sort(key=lambda s: s["combined_score"], reverse=True)

    if len(survivors) < min_approved_pairs:
        return {
            **empty_result,
            "combined_scores": combined_scores,
            "rejection_reason": (
                f"Only {len(survivors)} pair(s) qualified (minimum {min_approved_pairs})"
            ),
        }

    approved = survivors[:max_approved_pairs]
    return {
        **empty_result,
        "verdict": "approved",
        "approved_pairs": [s["pair"] for s in approved],
        "approved_count": len(approved),
        "combined_scores": combined_scores,
        "rejection_reason": None,
    }
