from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from .broker import TinkoffBroker
from .config import InstrumentConfig
from .rl_env import obs_from_candles


@dataclass
class Signal:
  figi: str
  side: str
  strength: float


class BaseStrategy(ABC):
  def __init__(self, instrument: InstrumentConfig, broker: TinkoffBroker):
    self.instrument = instrument
    self.broker = broker

  @abstractmethod
  def compute_signal(self, now: datetime) -> Signal:
    ...


class MeanReversionStrategy(BaseStrategy):
  def compute_signal(self, now: datetime) -> Signal:
    to_dt = now
    from_dt = to_dt - timedelta(days=self.instrument.strategy_params.get("lookback", 20) * 2)
    df = self.broker.get_historical_candles(self.instrument.figi, from_dt, to_dt)
    if len(df) < 10:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)

    lookback = self.instrument.strategy_params.get("lookback", 20)
    confirmation = self.instrument.strategy_params.get("confirmation_candles", 1)
    entry = self.instrument.strategy_params.get("zscore_entry", 1.0)
    exit_ = self.instrument.strategy_params.get("zscore_exit", 0.2)
    min_std_ratio = self.instrument.strategy_params.get("min_std_ratio", 0.0)
    prices = df["close"].tail(lookback + confirmation)
    if len(prices) < lookback + 1:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    mean = prices.iloc[:lookback].mean()
    std = prices.iloc[:lookback].std(ddof=1) or 1e-9
    if min_std_ratio > 0 and len(df["close"]) >= lookback * 2:
      long_series = df["close"].tail(lookback * 2).iloc[:-1]
      long_std = long_series.std(ddof=1) or 1e-9
      std = max(std, min_std_ratio * long_std)
    last = prices.iloc[-1]
    z = (last - mean) / std
    if confirmation > 1 and len(prices) >= lookback + confirmation:
      recent = prices.tail(confirmation)
      above = (recent > mean + entry * std).all()
      below = (recent < mean - entry * std).all()
      if not above and not below:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)

    if abs(z) < exit_:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    if z > entry:
      sig = Signal(figi=self.instrument.figi, side="sell", strength=float(min(1.0, z / 3)))
      logger.debug("MeanReversion %s: sell strength=%.2f z=%.2f", self.instrument.ticker, sig.strength, z)
      return sig
    if z < -entry:
      sig = Signal(figi=self.instrument.figi, side="buy", strength=float(min(1.0, abs(z) / 3)))
      logger.debug("MeanReversion %s: buy strength=%.2f z=%.2f", self.instrument.ticker, sig.strength, z)
      return sig
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class MomentumStrategy(BaseStrategy):
  def compute_signal(self, now: datetime) -> Signal:
    to_dt = now
    from_dt = to_dt - timedelta(days=self.instrument.strategy_params.get("lookback", 50) * 2)
    df = self.broker.get_historical_candles(self.instrument.figi, from_dt, to_dt)
    if len(df) < 10:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)

    lookback = self.instrument.strategy_params.get("lookback", 50)
    confirmation = self.instrument.strategy_params.get("confirmation_candles", 1)
    volume_mult = self.instrument.strategy_params.get("volume_mult", 0.0)
    if volume_mult > 0 and "volume" in df.columns and len(df) >= 21:
      vol_ma = df["volume"].tail(lookback + 20).iloc[:-1].rolling(20).mean().iloc[-1]
      if vol_ma and vol_ma > 0 and df["volume"].iloc[-1] < vol_ma * volume_mult:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    prices = df["close"].tail(lookback + confirmation)
    ret = prices.pct_change().dropna()
    total_ret = (1 + ret).prod() - 1
    threshold = self.instrument.strategy_params.get("threshold", 0.05)

    if confirmation > 1 and len(prices) >= confirmation + 1:
      recent = prices.tail(confirmation + 1).values
      ups = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
      downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
      if total_ret > threshold and downs > 0:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
      if total_ret < -threshold and ups > 0:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)

    if total_ret > threshold:
      sig = Signal(figi=self.instrument.figi, side="buy", strength=float(min(1.0, total_ret / 0.2)))
      logger.debug("Momentum %s: buy strength=%.2f ret=%.2f%%", self.instrument.ticker, sig.strength, total_ret * 100)
      return sig
    if total_ret < -threshold:
      sig = Signal(figi=self.instrument.figi, side="sell", strength=float(min(1.0, abs(total_ret) / 0.2)))
      logger.debug("Momentum %s: sell strength=%.2f ret=%.2f%%", self.instrument.ticker, sig.strength, total_ret * 100)
      return sig
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


def _get_candles(instrument: InstrumentConfig, broker: TinkoffBroker, lookback_days: int = 60) -> Optional[pd.DataFrame]:
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=lookback_days)
  try:
    df = broker.get_historical_candles(instrument.figi, from_dt, to_dt)
    return df if len(df) >= 10 else None
  except Exception as e:
    logger.debug("_get_candles %s: %s", getattr(instrument, "ticker", instrument.figi), e)
    return None


class RSIStrategy(BaseStrategy):
  """RSI: перекупленность (sell) / перепроданность (buy)."""
  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 50)
    if df is None:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    period = self.instrument.strategy_params.get("period", 14)
    overbought = self.instrument.strategy_params.get("overbought", 70)
    oversold = self.instrument.strategy_params.get("oversold", 30)
    use_ema = self.instrument.strategy_params.get("rsi_use_ema", False)
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    if use_ema:
      avg_gain = gain.ewm(span=period, adjust=False).mean()
      avg_loss = loss.ewm(span=period, adjust=False).mean()
    else:
      avg_gain = gain.rolling(period).mean()
      avg_loss = loss.rolling(period).mean()
    rs = avg_gain / (avg_loss.replace(0, 1e-9))
    rsi = 100 - (100 / (1 + rs))
    last_rsi = rsi.iloc[-1]
    if pd.isna(last_rsi):
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    if last_rsi >= overbought:
      strength = float(min(1.0, (last_rsi - overbought) / 30))
      logger.debug("RSI %s: sell strength=%.2f rsi=%.1f", self.instrument.ticker, strength, last_rsi)
      return Signal(figi=self.instrument.figi, side="sell", strength=strength)
    if last_rsi <= oversold:
      strength = float(min(1.0, (oversold - last_rsi) / 30))
      logger.debug("RSI %s: buy strength=%.2f rsi=%.1f", self.instrument.ticker, strength, last_rsi)
      return Signal(figi=self.instrument.figi, side="buy", strength=strength)
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class MACrossoverStrategy(BaseStrategy):
  """Пересечение быстрой и медленной MA: fast выше slow -> buy, ниже -> sell."""
  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 60)
    if df is None:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    fast = self.instrument.strategy_params.get("fast_period", 10)
    slow = self.instrument.strategy_params.get("slow_period", 30)
    close = df["close"]
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    if len(ma_fast) < slow + 1 or pd.isna(ma_fast.iloc[-2]) or pd.isna(ma_slow.iloc[-2]):
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    prev_fast, prev_slow = ma_fast.iloc[-2], ma_slow.iloc[-2]
    curr_fast, curr_slow = ma_fast.iloc[-1], ma_slow.iloc[-1]
    cross_up = prev_fast <= prev_slow and curr_fast > curr_slow
    cross_down = prev_fast >= prev_slow and curr_fast < curr_slow
    if cross_up:
      strength = float(min(1.0, (curr_fast - curr_slow) / (curr_slow or 1e-9) * 10))
      logger.debug("MA Crossover %s: buy strength=%.2f", self.instrument.ticker, strength)
      return Signal(figi=self.instrument.figi, side="buy", strength=min(1.0, max(0.3, strength)))
    if cross_down:
      strength = float(min(1.0, (curr_slow - curr_fast) / (curr_fast or 1e-9) * 10))
      logger.debug("MA Crossover %s: sell strength=%.2f", self.instrument.ticker, strength)
      return Signal(figi=self.instrument.figi, side="sell", strength=min(1.0, max(0.3, strength)))
    if curr_fast > curr_slow:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class BreakoutStrategy(BaseStrategy):
  """Цена вышла из диапазона (выше max или ниже min за lookback)."""
  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 60)
    if df is None:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    lookback = self.instrument.strategy_params.get("lookback", 20)
    atr_mult = self.instrument.strategy_params.get("atr_mult", 0.0)
    volume_mult = self.instrument.strategy_params.get("volume_mult", 0.0)
    if volume_mult > 0 and "volume" in df.columns and len(df) >= 21:
      vol_ma = df["volume"].tail(21).iloc[:-1].rolling(20).mean().iloc[-1]
      if vol_ma and vol_ma > 0 and df["volume"].iloc[-1] < vol_ma * volume_mult:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    prices = df["close"].tail(lookback + 1)
    if len(prices) < lookback + 1:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    window = prices.iloc[:-1]
    high, low = window.max(), window.min()
    last = prices.iloc[-1]
    if last > high:
      strength = float(min(1.0, (last - high) / (high or 1e-9) * 5))
      logger.debug("Breakout %s: buy strength=%.2f (above high)", self.instrument.ticker, strength)
      return Signal(figi=self.instrument.figi, side="buy", strength=max(0.3, strength))
    if last < low:
      strength = float(min(1.0, (low - last) / (low or 1e-9) * 5))
      logger.debug("Breakout %s: sell strength=%.2f (below low)", self.instrument.ticker, strength)
      return Signal(figi=self.instrument.figi, side="sell", strength=max(0.3, strength))
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class VolumeWeightedStrategy(BaseStrategy):
  """Сигнал только при объёме выше среднего (volume > volume_ma * mult). Подстраивает momentum."""
  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 50)
    if df is None or "volume" not in df.columns:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    vol_ma_period = self.instrument.strategy_params.get("volume_ma_period", 20)
    volume_mult = self.instrument.strategy_params.get("volume_mult", 1.2)
    lookback = self.instrument.strategy_params.get("lookback", 20)
    threshold = self.instrument.strategy_params.get("threshold", 0.03)
    df = df.tail(vol_ma_period + lookback)
    if len(df) < vol_ma_period + 5:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    vol_ma = df["volume"].iloc[:-1].rolling(vol_ma_period).mean().iloc[-1]
    last_vol = df["volume"].iloc[-1]
    if vol_ma <= 0 or last_vol < vol_ma * volume_mult:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    prices = df["close"].tail(lookback)
    ret = prices.pct_change().dropna()
    total_ret = (1 + ret).prod() - 1
    if total_ret > threshold:
      strength = float(min(1.0, total_ret / 0.2))
      return Signal(figi=self.instrument.figi, side="buy", strength=strength)
    if total_ret < -threshold:
      strength = float(min(1.0, abs(total_ret) / 0.2))
      return Signal(figi=self.instrument.figi, side="sell", strength=strength)
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class VolatilityRegimeStrategy(BaseStrategy):
  """При экстремальной волатильности (ATR) — hold; иначе можно делегировать подстратегии или ослаблять силу."""
  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 60)
    if df is None:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    atr_period = self.instrument.strategy_params.get("atr_period", 14)
    low_vol_pct = self.instrument.strategy_params.get("low_vol_pct", 0.3)
    high_vol_pct = self.instrument.strategy_params.get("high_vol_pct", 2.0)
    close = df["close"]
    high = df["high"] if "high" in df.columns else close
    low = df["low"] if "low" in df.columns else close
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.rolling(atr_period).mean()
    atr_pct = (atr / close * 100).dropna()
    if len(atr_pct) < 1:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    last_atr = atr_pct.iloc[-1]
    median_atr = atr_pct.rolling(min(20, len(atr_pct))).median().iloc[-1]
    if median_atr <= 0:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    ratio = last_atr / median_atr
    high_vol_hold = self.instrument.strategy_params.get("high_vol_hold", True)
    if ratio > high_vol_pct and high_vol_hold:
      logger.debug("VolatilityRegime %s: hold (high vol ratio=%.2f)", self.instrument.ticker, ratio)
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    sub = self.instrument.strategy_params.get("sub_strategy", "momentum")
    low_vol_strength_mult = self.instrument.strategy_params.get("low_vol_strength_mult", 0.7)
    try:
      base = _build_one(sub, self.instrument, self.broker)
      sig = base.compute_signal(now)
      if ratio < low_vol_pct and sig.side != "hold":
        sig = Signal(figi=sig.figi, side=sig.side, strength=min(1.0, sig.strength * low_vol_strength_mult))
      return sig
    except Exception as e:
      logger.debug("VolatilityRegime %s sub_strategy: %s", self.instrument.ticker, e)
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class MultiTFStrategy(BaseStrategy):
  """Фильтр по старшему таймфрейму: торговать только в сторону долгосрочного тренда.

  Использует более длинное окно по цене инструмента, затем пропускает сигналы подстратегии
  только в сторону тренда (up -> только buy, down -> только sell).
  """

  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 120)
    if df is None:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    lookback = self.instrument.strategy_params.get("higher_lookback", 40)
    trend_threshold = self.instrument.strategy_params.get("higher_trend_threshold", 0.04)
    sub = self.instrument.strategy_params.get("sub_strategy", "momentum")
    prices = df["close"].tail(lookback)
    if len(prices) < 2:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    ret = (prices.iloc[-1] / prices.iloc[0]) - 1
    if ret > trend_threshold:
      trend = "up"
    elif ret < -trend_threshold:
      trend = "down"
    else:
      trend = "flat"
    try:
      base = _build_one(sub, self.instrument, self.broker)
      sig = base.compute_signal(now)
    except Exception:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    if trend == "up" and sig.side == "sell":
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    if trend == "down" and sig.side == "buy":
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    return sig

class IndexStrategy(BaseStrategy):
  """Сигнал по индексу (например IMOEX): индекс в плюсе — разрешаем buy по бумаге, в минусе — sell."""
  def compute_signal(self, now: datetime) -> Signal:
    index_figi = self.instrument.strategy_params.get("index_figi")
    if not index_figi:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    lookback = self.instrument.strategy_params.get("lookback", 20)
    threshold = self.instrument.strategy_params.get("threshold", 0.02)
    to_dt = now
    from_dt = to_dt - timedelta(days=lookback * 2)
    try:
      idf = self.broker.get_historical_candles(index_figi, from_dt, to_dt)
    except Exception:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    if len(idf) < lookback + 1:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    prices = idf["close"].tail(lookback)
    ret = (prices.iloc[-1] / prices.iloc[0]) - 1
    if ret > threshold:
      strength = float(min(1.0, ret / 0.1))
      return Signal(figi=self.instrument.figi, side="buy", strength=strength)
    if ret < -threshold:
      strength = float(min(1.0, abs(ret) / 0.1))
      return Signal(figi=self.instrument.figi, side="sell", strength=strength)
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class TimeFilterStrategy(BaseStrategy):
  """Торгуем только в окне часов (Moscow). sub_strategy — базовая стратегия."""
  def compute_signal(self, now: datetime) -> Signal:
    start_h = self.instrument.strategy_params.get("trade_start_hour", 10)
    end_h = self.instrument.strategy_params.get("trade_end_hour", 18)
    h = now.hour
    if h < start_h or h > end_h:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    sub = self.instrument.strategy_params.get("sub_strategy", "momentum")
    try:
      return _build_one(sub, self.instrument, self.broker).compute_signal(now)
    except Exception:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class AdaptiveStrategy(BaseStrategy):
  """Робот сам анализирует режим рынка и выбирает стратегию: тренд -> momentum, флэт -> mean_reversion, пробой -> breakout, иначе голосование."""
  CANDIDATES = ("momentum", "mean_reversion", "breakout", "rsi")

  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 60)
    if df is None or len(df) < 25:
      try:
        return _build_one("momentum", self.instrument, self.broker).compute_signal(now)
      except Exception:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)

    lookback = self.instrument.strategy_params.get("lookback", 20)
    trend_threshold = self.instrument.strategy_params.get("trend_threshold", 0.04)
    z_flat_threshold = self.instrument.strategy_params.get("z_flat_threshold", 0.5)
    vol_flat_threshold = self.instrument.strategy_params.get("vol_flat_threshold", 0.02)
    prices = df["close"].tail(lookback)
    ret = (prices.iloc[-1] / prices.iloc[0]) - 1
    vol = prices.pct_change().std() or 1e-9
    mean = prices.mean()
    last = prices.iloc[-1]
    z = (last - mean) / (prices.std() or 1e-9) if len(prices) > 2 else 0
    high, low = prices.max(), prices.min()
    at_high = last >= high * 0.998
    at_low = last <= low * 1.002

    chosen = "momentum"
    if at_high or at_low:
      chosen = "breakout"
    elif abs(ret) > trend_threshold:
      chosen = "momentum"
    elif abs(z) < z_flat_threshold and vol < vol_flat_threshold:
      chosen = "mean_reversion"
    else:
      chosen = "rsi"

    try:
      strat = _build_one(chosen, self.instrument, self.broker)
      sig = strat.compute_signal(now)
      logger.debug("Adaptive %s: chosen=%s -> %s strength=%.2f", self.instrument.ticker, chosen, sig.side, sig.strength)
      return sig
    except Exception as e:
      logger.debug("Adaptive %s: %s failed (%s), fallback momentum", self.instrument.ticker, chosen, e)
      try:
        return _build_one("momentum", self.instrument, self.broker).compute_signal(now)
      except Exception:
        return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class DeepSeekStubStrategy(BaseStrategy):
  """Заглушка: сигнал по инструменту со стратегией deepseek формируется в portfolio из API DeepSeek."""
  def compute_signal(self, now: datetime) -> Signal:
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class RLStrategy(BaseStrategy):
  """Стратегия на признаках RL-окружения. Если задан rl_model_path и файл есть — используется обученная модель (PPO), иначе порог по доходности."""
  def __init__(self, instrument: InstrumentConfig, broker: TinkoffBroker):
    super().__init__(instrument, broker)
    self._model = None
    path = (instrument.strategy_params or {}).get("rl_model_path")
    if path and Path(path).exists():
      try:
        from stable_baselines3 import PPO
        self._model = PPO.load(path)
      except Exception as e:
        logger.debug("RL: не удалось загрузить модель %s: %s", path, e)

  def compute_signal(self, now: datetime) -> Signal:
    df = _get_candles(self.instrument, self.broker, 60)
    if df is None or len(df) < 50:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    obs = obs_from_candles(df, window=50)
    if self._model is not None:
      action, _ = self._model.predict(obs, deterministic=True)
      if action == 1:
        return Signal(figi=self.instrument.figi, side="buy", strength=0.7)
      if action == 2:
        return Signal(figi=self.instrument.figi, side="sell", strength=0.7)
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    # Fallback без модели: short momentum по средней доходности за окно (obs[0] — нормализованная)
    mean_return_signal = float(obs[0])
    threshold = self.instrument.strategy_params.get("threshold", 0.02)
    strength = min(1.0, abs(mean_return_signal) / max(threshold, 1e-9) * 0.5)
    if mean_return_signal > threshold:
      logger.debug("RL %s fallback (short momentum): buy strength=%.2f", self.instrument.ticker, strength)
      return Signal(figi=self.instrument.figi, side="buy", strength=strength)
    if mean_return_signal < -threshold:
      logger.debug("RL %s fallback (short momentum): sell strength=%.2f", self.instrument.ticker, strength)
      return Signal(figi=self.instrument.figi, side="sell", strength=strength)
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


class CombinedStrategy(BaseStrategy):
  """Взвешенное голосование стратегий: buy если сумма весов buy > 0.5, sell если сумма весов sell > 0.5."""

  def __init__(self, instrument: InstrumentConfig, broker: TinkoffBroker, names: List[str], weights: Optional[List[float]] = None):
    super().__init__(instrument, broker)
    self.strategies = [_build_one(n, instrument, broker) for n in names]
    n = len(self.strategies)
    if weights and len(weights) == n and abs(sum(weights) - 1.0) < 0.01:
      self.weights = [float(w) for w in weights]
    else:
      self.weights = [1.0 / n] * n

  def compute_signal(self, now: datetime) -> Signal:
    signals: List[Signal] = []
    for s in self.strategies:
      try:
        sig = s.compute_signal(now)
        signals.append(sig)
      except Exception as e:
        logger.debug("CombinedStrategy sub-signal: %s", e)
        continue
    if not signals:
      return Signal(figi=self.instrument.figi, side="hold", strength=0.0)
    w_buy = sum(self.weights[i] for i, s in enumerate(signals) if i < len(self.weights) and s.side == "buy")
    w_sell = sum(self.weights[i] for i, s in enumerate(signals) if i < len(self.weights) and s.side == "sell")
    if w_buy > 0.5:
      strength = sum(s.strength for i, s in enumerate(signals) if s.side == "buy" and i < len(self.weights)) / max(sum(1 for s in signals if s.side == "buy"), 1)
      return Signal(figi=self.instrument.figi, side="buy", strength=float(min(1.0, strength)))
    if w_sell > 0.5:
      strength = sum(s.strength for i, s in enumerate(signals) if s.side == "sell" and i < len(self.weights)) / max(sum(1 for s in signals if s.side == "sell"), 1)
      return Signal(figi=self.instrument.figi, side="sell", strength=float(min(1.0, strength)))
    return Signal(figi=self.instrument.figi, side="hold", strength=0.0)


def _build_one(name: str, instrument: InstrumentConfig, broker: TinkoffBroker) -> BaseStrategy:
  if name == "mean_reversion":
    return MeanReversionStrategy(instrument, broker)
  if name == "momentum":
    return MomentumStrategy(instrument, broker)
  if name == "rsi":
    return RSIStrategy(instrument, broker)
  if name == "ma_crossover":
    return MACrossoverStrategy(instrument, broker)
  if name == "breakout":
    return BreakoutStrategy(instrument, broker)
  if name == "volume_weighted":
    return VolumeWeightedStrategy(instrument, broker)
  if name == "volatility_regime":
    return VolatilityRegimeStrategy(instrument, broker)
  if name == "multi_tf":
    return MultiTFStrategy(instrument, broker)
  if name == "index":
    return IndexStrategy(instrument, broker)
  if name == "time_filter":
    return TimeFilterStrategy(instrument, broker)
  if name == "adaptive":
    return AdaptiveStrategy(instrument, broker)
  if name == "rl":
    return RLStrategy(instrument, broker)
  if name == "deepseek":
    # Реальный сигнал формируется в portfolio из DeepSeek API; здесь заглушка для CombinedStrategy и т.п.
    return DeepSeekStubStrategy(instrument, broker)
  raise ValueError(f"Unknown strategy: {name}")


def build_strategy(
  name: Union[str, List[str]], instrument: InstrumentConfig, broker: TinkoffBroker
) -> BaseStrategy:
  if isinstance(name, list):
    weights = (instrument.strategy_params or {}).get("combined_weights")
    return CombinedStrategy(instrument, broker, name, weights=weights)
  return _build_one(name, instrument, broker)

