"""Окружение для обучения с подкреплением (RL): симуляция торговли по историческим свечам."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces


@dataclass
class TradeState:
  equity: float
  position: int  # 0 flat, 1 long, -1 short
  step: int
  peak_equity: float


def _normalized_obs_from_window(close: pd.Series, window: pd.Series, returns: pd.Series) -> np.ndarray:
  """Признаки в нормализованном виде: доходности и z-score, без абсолютных цен."""
  if len(returns) < 10:
    return np.zeros(5, dtype=np.float32)
  mean_ret_5 = returns.rolling(5).mean().iloc[-1] if len(returns) >= 5 else 0.0
  std_ret_10 = returns.rolling(10).std().iloc[-1] if len(returns) >= 10 else 1e-9
  std_ret_10 = max(std_ret_10, 1e-9)
  # z-score последней доходности относительно окна
  z_return = (returns.iloc[-1] - returns.mean()) / (returns.std() or 1e-9)
  # нормализованная позиция цены в диапазоне окна (0..1)
  w_min, w_max = window.min(), window.max()
  if w_max > w_min:
    price_pos = (float(window.iloc[-1]) - w_min) / (w_max - w_min)
  else:
    price_pos = 0.5
  # волатильность окна (std доходностей), ограничиваем масштаб
  vol = float(np.clip(std_ret_10 * np.sqrt(252), 0.0, 2.0))
  feat = np.array(
    [
      float(np.clip(mean_ret_5, -0.5, 0.5)),
      vol,
      float(np.clip(z_return, -5.0, 5.0)),
      price_pos,
      float(np.clip(returns.iloc[-1], -0.2, 0.2)),
    ],
    dtype=np.float32,
  )
  return np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)


class TradingEnv(gym.Env):
  """Gymnasium-окружение: нормализованные признаки, комиссия, награда с учётом просадки."""

  metadata = {"render_modes": ["human"]}

  def __init__(
    self,
    df: pd.DataFrame,
    initial_capital: float = 100_000.0,
    commission_rate: float = 0.0003,
    reward_drawdown_penalty: float = 0.5,
  ):
    super().__init__()
    self.df = df.reset_index(drop=True).copy()
    if "close" not in self.df.columns and len(self.df.columns):
      self.df["close"] = self.df.iloc[:, 0]
    self.initial_capital = initial_capital
    self.commission_rate = commission_rate
    self.reward_drawdown_penalty = reward_drawdown_penalty

    self.observation_space = spaces.Box(
      low=-np.inf, high=np.inf, shape=(5,), dtype=np.float32
    )
    self.action_space = spaces.Discrete(3)

    self.state: TradeState | None = None
    self._window = 50

  def reset(self, seed: int | None = None, options=None) -> Tuple[np.ndarray, dict]:
    super().reset(seed=seed)
    self.state = TradeState(
      equity=self.initial_capital, position=0, step=self._window, peak_equity=self.initial_capital
    )
    return self._get_obs(), {}

  def _get_obs(self) -> np.ndarray:
    assert self.state is not None
    step = self.state.step
    close = self.df["close"]
    if step < self._window or step >= len(close):
      return np.zeros(5, dtype=np.float32)
    window = close.iloc[step - self._window : step]
    returns = window.pct_change().fillna(0.0)
    return _normalized_obs_from_window(close, window, returns)

  def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
    assert self.state is not None
    done = False
    step = self.state.step
    if step >= len(self.df) - 1:
      done = True
      return self._get_obs(), 0.0, done, False, {}

    price = float(self.df["close"].iloc[step])
    next_price = float(self.df["close"].iloc[step + 1])
    new_pos = {0: 0, 1: 1, 2: -1}[int(action)]

    pnl = (next_price - price) * self.state.position
    commission = 0.0
    if self.state.position != 0 and new_pos != self.state.position:
      commission += self.commission_rate * price * abs(self.state.position)
    if new_pos != 0 and new_pos != self.state.position:
      commission += self.commission_rate * next_price * abs(new_pos)
    equity = self.state.equity + pnl - commission
    peak = max(self.state.peak_equity, equity)
    dd = (peak - equity) / peak if peak > 0 else 0.0
    reward = (equity - self.state.equity) - self.reward_drawdown_penalty * dd

    self.state = TradeState(equity=equity, position=new_pos, step=step + 1, peak_equity=peak)
    obs = self._get_obs()
    if equity <= self.initial_capital * 0.5:
      done = True

    return obs, float(reward), done, False, {}


def obs_from_candles(df: pd.DataFrame, window: int = 50) -> np.ndarray:
  """По последним свечам построить вектор наблюдения (нормализованный, как в TradingEnv)."""
  if df is None or len(df) < window:
    return np.zeros(5, dtype=np.float32)
  close = df["close"].tail(window)
  returns = close.pct_change().fillna(0.0)
  return _normalized_obs_from_window(close, close, returns)
