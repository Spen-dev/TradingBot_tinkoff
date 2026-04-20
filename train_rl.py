#!/usr/bin/env python3
"""Обучение RL-агента (PPO) в TradingEnv и сохранение модели для стратегии rl."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from tinkoff_bot.config import load_config
from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.rl_env import TradingEnv

try:
  from stable_baselines3 import PPO
  from stable_baselines3.common.vec_env import DummyVecEnv
  SB3_AVAILABLE = True
except ImportError:
  SB3_AVAILABLE = False


def run_rl_train(
  broker: "TinkoffBroker",
  figi: str,
  days: int = 365,
  out_path: str | Path = "data/rl_model.zip",
  timesteps: int = 50_000,
  verbose: int = 1,
  commission_rate: float = 0.0003,
  reward_drawdown_penalty: float = 0.5,
  walk_forward_ratio: float = 0.7,
  tune_hyperparams: bool = False,
  optuna_trials: int = 20,
) -> str:
  """Обучить PPO по историческим данным. walk_forward_ratio — доля на обучение (остальное — out-of-sample проверка).
  tune_hyperparams: подбор lr, n_steps через Optuna."""
  if not SB3_AVAILABLE:
    return "Ошибка: установите pip install stable-baselines3"
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=days)
  df = broker.get_historical_candles(figi, from_dt, to_dt)
  if len(df) < 100:
    return f"Недостаточно данных для {figi} (n={len(df)})"

  split = int(len(df) * max(0.5, min(0.9, walk_forward_ratio)))
  df_train = df.iloc[:split]
  df_val = df.iloc[split:] if split < len(df) else df_train

  def make_env(data=None):
    d = data if data is not None else df_train
    return TradingEnv(
      d,
      initial_capital=100_000.0,
      commission_rate=commission_rate,
      reward_drawdown_penalty=reward_drawdown_penalty,
    )

  env = DummyVecEnv([lambda: make_env()])

  if tune_hyperparams and optuna_trials > 0:
    try:
      import optuna
      def objective(trial: Any) -> float:
        lr = trial.suggest_float("lr", 1e-4, 5e-4, log=True)
        n_steps = trial.suggest_categorical("n_steps", [128, 256, 512])
        batch = trial.suggest_categorical("batch_size", [32, 64, 128])
        if batch > n_steps:
          batch = n_steps
        model = PPO(
          "MlpPolicy", env, verbose=0,
          learning_rate=lr, n_steps=n_steps, batch_size=batch,
        )
        model.learn(total_timesteps=min(timesteps, 10_000))
        val_env = DummyVecEnv([lambda: make_env(df_val)])
        obs = val_env.reset()
        total_rew = 0.0
        for _ in range(min(len(df_val) - 1, 500)):
          action, _ = model.predict(obs, deterministic=True)
          obs, rewards, dones, _ = val_env.step(action)
          total_rew += float(rewards[0])
          if dones[0]:
            break
        return -total_rew
      study = optuna.create_study()
      study.optimize(objective, n_trials=optuna_trials, show_progress_bar=True)
      best = study.best_params
      lr = best.get("lr", 3e-4)
      n_steps = best.get("n_steps", 256)
      batch = best.get("batch_size", 64)
    except ImportError:
      lr, n_steps, batch = 3e-4, 256, 64
  else:
    lr, n_steps, batch = 3e-4, 256, 64

  model = PPO(
    "MlpPolicy", env, verbose=verbose,
    learning_rate=lr, n_steps=n_steps, batch_size=batch,
  )
  model.learn(total_timesteps=timesteps)
  path = Path(out_path)
  path.parent.mkdir(parents=True, exist_ok=True)
  model.save(str(path))
  meta: Dict[str, Any] = {
    "date": datetime.now().isoformat(),
    "days": days,
    "timesteps": timesteps,
    "figi": figi,
    "walk_forward_ratio": walk_forward_ratio,
    "commission_rate": commission_rate,
    "reward_drawdown_penalty": reward_drawdown_penalty,
    "learning_rate": lr,
    "n_steps": n_steps,
    "batch_size": batch,
  }
  path_meta = path.with_suffix(".json")
  path_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
  return f"Модель сохранена: {path} (figi={figi}, {timesteps} шагов)"


def main() -> None:
  parser = argparse.ArgumentParser(description="Train RL agent for trading")
  parser.add_argument("--figi", default="BBG004730ZJ9", help="FIGI for training data")
  parser.add_argument("--days", type=int, default=365, help="Days of history")
  parser.add_argument("--out", default="data/rl_model.zip", help="Output model path")
  parser.add_argument("--timesteps", type=int, default=50_000, help="Training timesteps")
  parser.add_argument("--commission", type=float, default=0.0003, help="Commission rate for env")
  parser.add_argument("--walk-forward", type=float, default=0.7, help="Train ratio (rest = validation)")
  parser.add_argument("--tune", action="store_true", help="Tune PPO hyperparams with Optuna")
  parser.add_argument("--optuna-trials", type=int, default=20, help="Optuna trials when --tune")
  args = parser.parse_args()

  if not SB3_AVAILABLE:
    print("Установите: pip install stable-baselines3")
    return

  base_dir = Path(__file__).resolve().parent
  cfg = load_config(str(base_dir / "config.yaml"))
  broker = TinkoffBroker(cfg.tinkoff)
  res = run_rl_train(
    broker, args.figi, days=args.days, out_path=args.out, timesteps=args.timesteps,
    commission_rate=args.commission, walk_forward_ratio=args.walk_forward,
    tune_hyperparams=args.tune, optuna_trials=args.optuna_trials,
  )
  print(res)


if __name__ == "__main__":
  main()
