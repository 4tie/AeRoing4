from __future__ import annotations

import asyncio


class _MockStdout:
    def __init__(self, text: str) -> None:
        self._lines = [f"{line}\n".encode() for line in text.splitlines()]

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if not self._lines:
            return b""
        return self._lines.pop(0)


class MockAsyncProcess:
    def __init__(self, *, stdout_data: str = "", return_code: int = 0) -> None:
        self.pid = 12345
        self.returncode = None
        self._return_code = return_code
        self.stdout = _MockStdout(stdout_data)

    async def wait(self) -> int:
        await asyncio.sleep(0)
        self.returncode = self._return_code
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def create_backtest_result(
    *,
    profit: float = 0.05,
    max_dd: float = 0.10,
    trades: int = 42,
    win_rate: float = 0.55,
) -> str:
    return "\n".join(
        [
            "Backtesting with data from 2023-01-01 up to 2024-01-01",
            f"Total profit % | {profit * 100:.2f}",
            f"Absolute profit | {profit:.4f} USDT",
            f"Max % of account underwater | {max_dd * 100:.2f}%",
            f"Total/Daily Avg Trades | {trades}",
            f"Winrate | {win_rate * 100:.2f}%",
        ]
    )


def create_backtest_output(*, include_hyperopt: bool = False, epochs: int = 10) -> str:
    lines = ["Hyperopt started"]
    if include_hyperopt:
        for epoch in range(1, epochs + 1):
            lines.append(
                f"{epoch}/{epochs}: {20 + epoch} trades. "
                f"Avg profit 0.{epoch:02d}%. Total profit {epoch * 0.1:.4f} USDT. "
                f"Objective: {-epoch * 0.01:.4f}"
            )
        lines.append("Best result:")
        lines.append('{"params": {"buy": {}, "sell": {}, "roi": {}, "stoploss": -0.1}}')
    return "\n".join(lines)
