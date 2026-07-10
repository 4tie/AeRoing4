"""ParsedSummary <-> CanonicalMetricsSnapshot compatibility tests (Prompt 2 §8).

For the same backtest artifact, the existing ParsedSummary values and the
canonical metrics snapshot must agree for equivalent metrics, since the
adapter is a pure pass-through (no recalculation) for these fields.
"""

from backend.models.runs import ParsedSummary
from backend.services.aeroing4.metrics.adapters import from_parsed_summary


def _summary() -> ParsedSummary:
    return ParsedSummary(
        run_id="run-compat-1",
        starting_balance=1000.0,
        final_balance=1250.0,
        net_profit_currency=250.0,
        net_profit_pct=25.0,
        total_trades=40,
        trades_per_day=4.0,
        win_rate_pct=55.0,
        loss_rate_pct=45.0,
        max_drawdown_pct=10.5,
        max_drawdown_currency=105.0,
        avg_trade_duration_minutes=52.5,
        profit_factor=1.65,
        expectancy=6.25,
        sharpe_ratio=1.1,
        sortino_ratio=1.4,
        calmar_ratio=2.3,
        exit_reason_distribution=[],
    )


class TestParsedSummaryCompatibility:
    def setup_method(self):
        self.summary = _summary()
        self.snapshot = from_parsed_summary(self.summary)

    def test_net_profit_agrees(self):
        assert self.snapshot.net_profit_abs.value == self.summary.net_profit_currency
        assert self.snapshot.net_profit_pct.value == self.summary.net_profit_pct

    def test_win_rate_agrees(self):
        assert self.snapshot.win_rate.value == self.summary.win_rate_pct

    def test_max_drawdown_agrees(self):
        assert self.snapshot.max_drawdown_pct.value == self.summary.max_drawdown_pct
        assert self.snapshot.max_drawdown_abs.value == self.summary.max_drawdown_currency

    def test_average_trade_duration_agrees(self):
        assert (
            self.snapshot.average_trade_duration_minutes.value
            == self.summary.avg_trade_duration_minutes
        )

    def test_profit_factor_agrees(self):
        assert self.snapshot.profit_factor.value == self.summary.profit_factor

    def test_expectancy_agrees(self):
        assert self.snapshot.expectancy.value == self.summary.expectancy

    def test_sharpe_sortino_calmar_agree(self):
        assert self.snapshot.sharpe.value == self.summary.sharpe_ratio
        assert self.snapshot.sortino.value == self.summary.sortino_ratio
        assert self.snapshot.calmar.value == self.summary.calmar_ratio

    def test_units_are_explicit_0_to_100_for_percentages(self):
        """Regression guard: percentages must never silently flip to 0-1."""
        assert self.summary.net_profit_pct > 1  # sanity: this fixture is 25.0, not 0.25
        assert self.snapshot.net_profit_pct.value == self.summary.net_profit_pct
        assert self.snapshot.win_rate.value == self.summary.win_rate_pct
        assert self.snapshot.max_drawdown_pct.value == self.summary.max_drawdown_pct
