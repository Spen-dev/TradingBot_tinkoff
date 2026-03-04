from prometheus_client import Counter, Gauge, Histogram

equity_gauge = Gauge("bot_equity", "Current portfolio equity")
drawdown_gauge = Gauge("bot_drawdown", "Current max drawdown")
trade_counter = Counter("bot_trades_total", "Total trades executed")
error_counter = Counter("bot_errors_total", "Total errors")
slippage_pct_histogram = Histogram(
  "bot_slippage_pct",
  "Slippage (limit vs expected price) in percent",
  ["direction"],
  buckets=(0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05),
)


def update_equity(equity: float, drawdown: float) -> None:
  equity_gauge.set(equity)
  drawdown_gauge.set(drawdown)


def inc_trades(n: int = 1) -> None:
  trade_counter.inc(n)


def inc_error() -> None:
  error_counter.inc()


def observe_slippage_pct(direction: str, slippage_pct: float) -> None:
  """direction: 'buy' или 'sell'."""
  slippage_pct_histogram.labels(direction=direction).observe(abs(slippage_pct))

