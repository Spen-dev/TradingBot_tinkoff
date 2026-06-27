import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Union

import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


@dataclass
class InstrumentConfig:
  figi: str
  ticker: str
  strategy: Union[str, List[str]]
  target_weight: float
  strategy_params: Dict[str, Any]
  lot: int = 1  # размер лота (1, 10, 100) — для округления заявок


@dataclass
class RiskConfig:
  max_drawdown: float
  daily_loss_limit: float
  default_stop_loss_pct: float
  trailing_stop_pct: float
  var_confidence: float
  kelly_fraction_cap: float
  # Мягкая деградация при дневном убытке: сначала уменьшаем размер сделок, потом полный стоп.
  daily_loss_soft_limit: float = 0.0  # 0 = выкл; >0 = включить мягкое снижение размера при превышении этого порога
  daily_loss_soft_scale: float = 0.5  # во сколько раз уменьшать размер заявок при soft-limit (0.5 = вдвое)
  pause_after_consecutive_losses: int = 0
  pause_hours: float = 24
  min_pnl_to_count_loss_rub: float = 0.0
  take_profit_pct: float = 0.03
  trailing_take_profit_pct: float = 0.02


@dataclass
class TelegramConfig:
  token: str
  admin_chat_id: int


@dataclass
class WebConfig:
  host: str
  port: int
  dashboard_url: str = ""  # URL дашборда для кнопки в Telegram (например http://IP:8000/dashboard)


@dataclass
class TinkoffConfig:
  token: str
  account_id: str
  use_sandbox: bool


@dataclass
class DynamicPortfolioConfig:
  """Динамический состав портфеля по советам DeepSeek / Finam."""
  enabled: bool = False
  candidates: List[str] = field(default_factory=list)
  max_instruments: int = 6
  min_instruments: int = 4
  max_weight_per_instrument: float = 0.30
  refresh_interval_days: int = 7
  default_strategy: str = "deepseek"
  fallback_to_static: bool = True
  state_file: str = "data/dynamic_portfolio.json"
  use_deepseek: bool = True
  use_finam: bool = True
  use_moex: bool = True
  use_gemini: bool = True
  use_groq: bool = True
  pick_best_advisor: bool = True


@dataclass
class FinamConfig:
  api_token: str = ""
  base_url: str = "https://api.finam.ru"
  exchange_mic: str = "MISX"


@dataclass
class MoexConfig:
  base_url: str = "https://iss.moex.com/iss"
  board: str = "TQBR"


@dataclass
class GeminiConfig:
  api_key: str = ""
  model: str = "gemini-2.0-flash"


@dataclass
class GroqConfig:
  api_key: str = ""
  model: str = "llama-3.3-70b-versatile"


@dataclass
class PortfolioConfig:
  base_currency: str
  rebalance_frequency: str
  rebalance_time: str
  commission_rate: float
  dry_run: bool = False
  limit_price_pct: float = 0.001  # по умолчанию для покупок и продаж
  limit_price_pct_buy: float = 0.0   # 0 = использовать limit_price_pct
  limit_price_pct_sell: float = 0.0  # 0 = использовать limit_price_pct
  cancel_open_orders_before_rebalance: bool = True
  rebalance_by_price: bool = False
  rebalance_on_drift: bool = True
  rebalance_drift_pct: float = 0.05
  rebalance_check_interval_minutes: int = 30
  rebalance_cooldown_minutes: int = 60
  # true = расписание/дрейф/прочий цикл планировщика без Telegram «Старт» (удобно после перезапуска Docker)
  auto_rebalance_when_stopped: bool = False
  rebalance_interval_hours: float = 0.0  # 0 = раз в день по rebalance_time, >0 = каждые N часов в окне
  retrain_days: int = 60
  auto_retrain_interval_days: int = 0
  volatility_atr_period: int = 14
  watchdog_interval_seconds: int = 90
  request_timeout_seconds: float = 30.0  # таймаут вызовов брокера в планировщике и watchdog
  trading_enabled: bool = True
  alert_cooldown_minutes: int = 30
  no_trades_alert_hours: int = 0
  daily_digest_time: str = "18:00"
  # RL: автообучение стратегии rl
  rl_train_on_start: bool = False
  rl_train_interval_days: int = 0  # 0 = только вручную / по расписанию при старте
  rl_train_days: int = 365
  rl_train_timesteps: int = 50_000
  rl_train_walk_forward_ratio: float = 0.7
  # Самообучение: расширенные опции
  self_learn_train_ratio: float = 0.7
  self_learn_use_sharpe: bool = True
  self_learn_min_trades: int = 5
  self_learn_risk_penalty: float = 0.5
  self_learn_optuna_trials: int = 0  # 0 = перебор по сетке, >0 = Optuna
  self_learn_optimize_weights: bool = False
  self_learn_weight_cap: float = 0.4
  rebalance_window_start_minutes: int = 0  # устарело, на окно ребаланса не влияет
  rebalance_window_end_minutes: int = 1090
  trading_timezone: str = ""  # например Europe/Moscow; пусто = локальное время сервера
  volume_filter_min_ratio: float = 0.0
  atr_percentile_days: int = 90
  use_market_regime: bool = True
  use_market_regime_by_index: bool = False  # единый режим по market_index_figi для всех инструментов
  adx_period: int = 14
  adx_threshold: float = 25.0
  adx_threshold_low: float = 0.0  # 0 = авто (0.8*threshold); иначе нижний порог для weak_trend
  self_learn_tune_by_regime: bool = False
  signal_strength_mult: float = 0.2  # множитель силы сигнала на размер (buy: 1+mult*strength, sell: 1-mult*strength)
  signal_strength_min: float = 0.3  # минимальная сила для расчёта размера заявки
  max_overweight_without_signal_pct: float = 0.0  # при перевесе > N% разрешать сокращение без сигнала sell (0=выкл)
  use_order_book_for_limits: bool = False  # использовать стакан (bid/ask/mid) при расчёте лимитной цены
  # rebalance_interval_hours объявлен выше (дублирование поля ломало dataclass в части сред)
  market_index_figi: str = ""           # FIGI индекса рынка (например IMOEX), для kill-switch и оценки волатильности
  market_panic_drop_pct: float = 0.05   # дневное падение индекса (в долях), при котором включается глобальная пауза
  market_vol_low_threshold_pct: float = 0.01   # |дневное изм.| ниже этого — низкая волатильность
  market_vol_high_threshold_pct: float = 0.03  # |дневное изм.| выше этого — высокая волатильность
  single_trade_max_pct: float = 0.0
  max_position_pct: float = 0.0
  hold_timeout_days: int = 0
  instrument_pause_after_losses: int = 0
  instrument_pause_hours: float = 24.0
  signal_confirmation_candles: int = 0
  weekly_report_weekday: int = 6
  weekly_report_time: str = "18:00"
  use_candle_cache: bool = False
  candle_cache_days: int = 60
  gap_risk_enabled: bool = False
  gap_min_pct: float = 0.03
  gap_close_minutes: int = 60
  no_new_orders_before_end_minutes: int = 0  # в последние N минут окна не выставлять новые лимитные покупки (0 = выкл)
  alert_drawdown_pct: float = 0.0   # алерт при просадке >= N% (0 = выкл)
  alert_daily_loss_pct: float = 0.0  # алерт при дневном убытке >= N% от старта дня (0 = выкл)
  alert_live_ping_hours: float = 0.0  # раз в N часов отправлять «Робот работает» (0 = выкл)
  use_deepseek_advisor: bool = False  # DeepSeek для рекомендаций
  use_finam_advisor: bool = False  # Finam Trade API: количественные сигналы
  use_moex_advisor: bool = True  # MOEX ISS: бесплатные количественные сигналы
  use_gemini_advisor: bool = True  # Google Gemini LLM
  use_groq_advisor: bool = True  # Groq LLM (Llama)
  pick_best_advisor: bool = True  # выбрать лучший советник
  deepseek_model: str = "deepseek-chat"
  gemini_model: str = "gemini-2.0-flash"
  groq_model: str = "llama-3.3-70b-versatile"
  llm_cache_hours: float = 2.0  # кэш Gemini/Groq (часы)
  auto_strategy_selection_on_start: bool = False  # при старте робота один раз выбрать лучшую стратегию по бэктесту для каждого инструмента
  strategy_selection_days: int = 90  # глубина истории (дней) для выбора стратегии
  strategy_selection_interval_days: int = 0  # пересчёт выбора стратегии раз в N дней (0 = только при старте и вручную)
  strategy_change_min_delta: float = 0.05  # не менять стратегию, если прирост оценки меньше этого порога
  strategy_diversity_max_share: float = 0.0  # макс. доля портфеля у одной стратегии, 0 = не ограничивать (0.5 = 50%)
  deepseek_cache_hours: float = 2.0  # кэш рекомендаций DeepSeek (часы), 0 = не кэшировать
  deepseek_history_days: int = 10  # дней истории (доходность, волатильность) в контексте для DeepSeek
  rebalance_decisions_log: bool = True  # писать в лог решения ребаланса (стратегия, сигнал, заявки)
  aggressive_rebalance: bool = False  # максимально агрессивный ребаланс по весам (ослабить фильтры по сигналам/отклонению)
  log_retention_days: int = 14  # хранить ротированные bot.log.*; автоочистка раз в сутки

  def rebalance_day_minutes_window(self) -> tuple[int, int]:
    """Минуты суток [lo, hi] включительно, когда разрешён ребаланс.

    Начало: время rebalance_time (слот «в 10:00» — с 10:00, без сдвига).
    Конец: rebalance_window_end_minutes (минуты от полуночи, см. yaml).

    rebalance_window_start_minutes оставлен в конфиге для совместимости; на границы окна не влияет.

    Если rebalance_time по минутам позже конца (часто при ~18:00 и end ~1090≈18:10),
    конец переносится на 23:59 — иначе окно пустое и авторебаланс не срабатывает.
    """
    try:
      rh, rm = map(int, str(self.rebalance_time).strip().split(":"))
    except (ValueError, AttributeError):
      rh, rm = 10, 0
    rt_m = rh * 60 + rm
    we = int(self.rebalance_window_end_minutes or 24 * 60)
    if we >= 24 * 60:
      return 0, 24 * 60 - 1
    lo = rt_m
    hi = we
    if lo > hi:
      hi = 24 * 60 - 1
    lo = max(0, min(lo, 24 * 60 - 1))
    hi = max(lo, min(hi, 24 * 60 - 1))
    return lo, hi


@dataclass
class AppConfig:
  mode: str
  tinkoff: TinkoffConfig
  portfolio: PortfolioConfig
  risk: RiskConfig
  telegram: TelegramConfig
  web: WebConfig
  instruments: List[InstrumentConfig]
  dynamic_portfolio: DynamicPortfolioConfig | None = None
  finam: FinamConfig | None = None
  moex: MoexConfig | None = None
  gemini: GeminiConfig | None = None
  groq: GroqConfig | None = None


def load_config(path: str = "config.yaml") -> AppConfig:
  with open(path, "r", encoding="utf-8") as f:
    raw = yaml.safe_load(f)

  tinkoff = TinkoffConfig(
    token=os.getenv("TINKOFF_TOKEN", raw["tinkoff"]["token"]),
    account_id=os.getenv("TINKOFF_ACCOUNT_ID", raw["tinkoff"]["account_id"]),
    use_sandbox=raw["tinkoff"].get("use_sandbox", True),
  )

  telegram = TelegramConfig(
    token=os.getenv("TELEGRAM_TOKEN", raw["telegram"]["token"]),
    admin_chat_id=int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", raw["telegram"]["admin_chat_id"])),
  )

  p_raw = raw.get("portfolio", {})
  mode = raw.get("mode", p_raw.get("mode", "sandbox"))
  # Песочница: без ключа в yaml включать цикл без кнопки «Старт» (на сервере часто забывают ключ).
  if "auto_rebalance_when_stopped" in p_raw:
    auto_rebalance_when_stopped = bool(p_raw.get("auto_rebalance_when_stopped"))
  else:
    auto_rebalance_when_stopped = str(mode).lower() == "sandbox"
  portfolio = PortfolioConfig(
    base_currency=p_raw.get("base_currency", "RUB"),
    rebalance_frequency=p_raw.get("rebalance_frequency", "daily"),
    rebalance_time=p_raw.get("rebalance_time", "10:00"),
    commission_rate=p_raw.get("commission_rate", 0.0003),
    dry_run=os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes") or p_raw.get("dry_run", False),
    limit_price_pct=p_raw.get("limit_price_pct", 0.001),
    limit_price_pct_buy=float(p_raw.get("limit_price_pct_buy", 0)),
    limit_price_pct_sell=float(p_raw.get("limit_price_pct_sell", 0)),
    cancel_open_orders_before_rebalance=p_raw.get("cancel_open_orders_before_rebalance", True),
    use_order_book_for_limits=p_raw.get("use_order_book_for_limits", False),
    rebalance_by_price=p_raw.get("rebalance_by_price", False),
    rebalance_on_drift=p_raw.get("rebalance_on_drift", True),
    rebalance_drift_pct=p_raw.get("rebalance_drift_pct", 0.05),
    rebalance_check_interval_minutes=p_raw.get("rebalance_check_interval_minutes", 30),
    rebalance_cooldown_minutes=p_raw.get("rebalance_cooldown_minutes", 60),
    auto_rebalance_when_stopped=auto_rebalance_when_stopped,
    rebalance_interval_hours=p_raw.get("rebalance_interval_hours", 0.0),
    retrain_days=p_raw.get("retrain_days", 60),
    auto_retrain_interval_days=p_raw.get("auto_retrain_interval_days", 0),
    volatility_atr_period=p_raw.get("volatility_atr_period", 14),
    watchdog_interval_seconds=p_raw.get("watchdog_interval_seconds", 90),
    request_timeout_seconds=float(p_raw.get("request_timeout_seconds", 30)),
    trading_enabled=p_raw.get("trading_enabled", True),
    alert_cooldown_minutes=p_raw.get("alert_cooldown_minutes", 30),
    no_trades_alert_hours=p_raw.get("no_trades_alert_hours", 0),
    daily_digest_time=p_raw.get("daily_digest_time", "18:00"),
    rl_train_on_start=p_raw.get("rl_train_on_start", False),
    rl_train_interval_days=p_raw.get("rl_train_interval_days", 0),
    rl_train_days=p_raw.get("rl_train_days", 365),
    rl_train_timesteps=p_raw.get("rl_train_timesteps", 50_000),
    self_learn_train_ratio=p_raw.get("self_learn_train_ratio", 0.7),
    self_learn_use_sharpe=p_raw.get("self_learn_use_sharpe", True),
    self_learn_min_trades=p_raw.get("self_learn_min_trades", 5),
    self_learn_risk_penalty=p_raw.get("self_learn_risk_penalty", 0.5),
    self_learn_optuna_trials=p_raw.get("self_learn_optuna_trials", 0),
    self_learn_optimize_weights=p_raw.get("self_learn_optimize_weights", False),
    self_learn_weight_cap=p_raw.get("self_learn_weight_cap", 0.4),
    rebalance_window_start_minutes=p_raw.get("rebalance_window_start_minutes", 0),
    rebalance_window_end_minutes=p_raw.get("rebalance_window_end_minutes", 1090),
    trading_timezone=p_raw.get("trading_timezone", ""),
    volume_filter_min_ratio=p_raw.get("volume_filter_min_ratio", 0.0),
    atr_percentile_days=p_raw.get("atr_percentile_days", 90),
    use_market_regime=p_raw.get("use_market_regime", True),
    use_market_regime_by_index=p_raw.get("use_market_regime_by_index", False),
    adx_period=p_raw.get("adx_period", 14),
    adx_threshold=p_raw.get("adx_threshold", 25.0),
    adx_threshold_low=p_raw.get("adx_threshold_low", 0.0),
    self_learn_tune_by_regime=p_raw.get("self_learn_tune_by_regime", False),
    signal_strength_mult=p_raw.get("signal_strength_mult", 0.2),
    signal_strength_min=p_raw.get("signal_strength_min", 0.3),
    max_overweight_without_signal_pct=p_raw.get("max_overweight_without_signal_pct", 0.0),
    rl_train_walk_forward_ratio=p_raw.get("rl_train_walk_forward_ratio", 0.7),
    market_index_figi=p_raw.get("market_index_figi", ""),
    market_panic_drop_pct=p_raw.get("market_panic_drop_pct", 0.05),
    market_vol_low_threshold_pct=p_raw.get("market_vol_low_threshold_pct", 0.01),
    market_vol_high_threshold_pct=p_raw.get("market_vol_high_threshold_pct", 0.03),
    single_trade_max_pct=p_raw.get("single_trade_max_pct", 0.0),
    max_position_pct=p_raw.get("max_position_pct", 0.0),
    hold_timeout_days=p_raw.get("hold_timeout_days", 0),
    instrument_pause_after_losses=p_raw.get("instrument_pause_after_losses", 0),
    instrument_pause_hours=p_raw.get("instrument_pause_hours", 24.0),
    signal_confirmation_candles=p_raw.get("signal_confirmation_candles", 0),
    weekly_report_weekday=p_raw.get("weekly_report_weekday", 6),
    weekly_report_time=p_raw.get("weekly_report_time", "18:00"),
    use_candle_cache=p_raw.get("use_candle_cache", False),
    candle_cache_days=p_raw.get("candle_cache_days", 60),
    gap_risk_enabled=p_raw.get("gap_risk_enabled", False),
    gap_min_pct=p_raw.get("gap_min_pct", 0.03),
    gap_close_minutes=p_raw.get("gap_close_minutes", 60),
    no_new_orders_before_end_minutes=p_raw.get("no_new_orders_before_end_minutes", 0),
    alert_drawdown_pct=p_raw.get("alert_drawdown_pct", 0.0),
    alert_daily_loss_pct=p_raw.get("alert_daily_loss_pct", 0.0),
    alert_live_ping_hours=p_raw.get("alert_live_ping_hours", 0.0),
    use_deepseek_advisor=p_raw.get("use_deepseek_advisor", False),
    use_finam_advisor=p_raw.get("use_finam_advisor", False),
    use_moex_advisor=p_raw.get("use_moex_advisor", True),
    use_gemini_advisor=p_raw.get("use_gemini_advisor", True),
    use_groq_advisor=p_raw.get("use_groq_advisor", True),
    pick_best_advisor=p_raw.get("pick_best_advisor", True),
    deepseek_model=p_raw.get("deepseek_model", "deepseek-chat"),
    gemini_model=p_raw.get("gemini_model", "gemini-2.0-flash"),
    groq_model=p_raw.get("groq_model", "llama-3.3-70b-versatile"),
    llm_cache_hours=float(p_raw.get("llm_cache_hours", 2.0) or 2.0),
    auto_strategy_selection_on_start=p_raw.get("auto_strategy_selection_on_start", False),
    strategy_selection_days=p_raw.get("strategy_selection_days", 90),
    strategy_selection_interval_days=p_raw.get("strategy_selection_interval_days", 0),
    strategy_change_min_delta=p_raw.get("strategy_change_min_delta", 0.05),
    strategy_diversity_max_share=p_raw.get("strategy_diversity_max_share", 0.0),
    deepseek_cache_hours=p_raw.get("deepseek_cache_hours", 2.0),
    deepseek_history_days=p_raw.get("deepseek_history_days", 10),
    rebalance_decisions_log=p_raw.get("rebalance_decisions_log", True),
    aggressive_rebalance=p_raw.get("aggressive_rebalance", False),
    log_retention_days=int(p_raw.get("log_retention_days", 14) or 14),
  )
  risk_raw = raw.get("risk", {})
  risk_raw.setdefault("pause_after_consecutive_losses", 0)
  risk_raw.setdefault("pause_hours", 24)
  risk_raw.setdefault("min_pnl_to_count_loss_rub", 0.0)
  risk_raw.setdefault("take_profit_pct", 0.03)
  risk_raw.setdefault("trailing_take_profit_pct", 0.02)
  risk = RiskConfig(**risk_raw)
  web_raw = {**{"host": "0.0.0.0", "port": 8000, "dashboard_url": ""}, **raw.get("web", {})}
  if os.getenv("DASHBOARD_URL"):
    web_raw["dashboard_url"] = os.getenv("DASHBOARD_URL", "").strip()
  web = WebConfig(**web_raw)

  instruments = []
  for i in raw.get("instruments") or []:
    d = dict(i)
    d.setdefault("lot", 1)
    d.setdefault("strategy_params", {})
    instruments.append(InstrumentConfig(**d))

  dp_raw = raw.get("dynamic_portfolio") or {}
  dynamic_portfolio = DynamicPortfolioConfig(
    enabled=bool(dp_raw.get("enabled", False)),
    candidates=[str(t).upper() for t in (dp_raw.get("candidates") or [])],
    max_instruments=int(dp_raw.get("max_instruments", 6) or 6),
    min_instruments=int(dp_raw.get("min_instruments", 4) or 4),
    max_weight_per_instrument=float(dp_raw.get("max_weight_per_instrument", 0.30) or 0.30),
    refresh_interval_days=int(dp_raw.get("refresh_interval_days", 7) or 7),
    default_strategy=str(dp_raw.get("default_strategy", "deepseek") or "deepseek"),
    fallback_to_static=bool(dp_raw.get("fallback_to_static", True)),
    state_file=str(dp_raw.get("state_file", "data/dynamic_portfolio.json") or "data/dynamic_portfolio.json"),
    use_deepseek=bool(dp_raw.get("use_deepseek", True)),
    use_finam=bool(dp_raw.get("use_finam", True)),
    use_moex=bool(dp_raw.get("use_moex", True)),
    use_gemini=bool(dp_raw.get("use_gemini", True)),
    use_groq=bool(dp_raw.get("use_groq", True)),
    pick_best_advisor=bool(dp_raw.get("pick_best_advisor", True)),
  )

  fm_raw = raw.get("finam") or {}
  finam = FinamConfig(
    api_token=os.getenv("FINAM_API_TOKEN", fm_raw.get("api_token", "")),
    base_url=str(fm_raw.get("base_url", "https://api.finam.ru") or "https://api.finam.ru"),
    exchange_mic=str(fm_raw.get("exchange_mic", "MISX") or "MISX"),
  )

  mx_raw = raw.get("moex") or {}
  moex = MoexConfig(
    base_url=str(mx_raw.get("base_url", "https://iss.moex.com/iss") or "https://iss.moex.com/iss"),
    board=str(mx_raw.get("board", "TQBR") or "TQBR"),
  )

  gm_raw = raw.get("gemini") or {}
  gemini = GeminiConfig(
    api_key=os.getenv("GEMINI_API_KEY", gm_raw.get("api_key", "")),
    model=str(gm_raw.get("model", "gemini-2.0-flash") or "gemini-2.0-flash"),
  )

  gq_raw = raw.get("groq") or {}
  groq = GroqConfig(
    api_key=os.getenv("GROQ_API_KEY", gq_raw.get("api_key", "")),
    model=str(gq_raw.get("model", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile"),
  )

  return AppConfig(
    mode=mode,
    tinkoff=tinkoff,
    portfolio=portfolio,
    risk=risk,
    telegram=telegram,
    web=web,
    instruments=instruments,
    dynamic_portfolio=dynamic_portfolio,
    finam=finam,
    moex=moex,
    gemini=gemini,
    groq=groq,
  )


VALID_STRATEGIES = (
  "mean_reversion", "momentum", "rsi", "ma_crossover", "breakout",
  "volume_weighted", "volatility_regime", "index", "time_filter", "adaptive", "rl", "deepseek",
)


def validate_config(cfg: "AppConfig") -> tuple[bool, list[str]]:
  """Проверка конфига и learned_params. Возвращает (ok, список ошибок)."""
  errors: list[str] = []
  if not (cfg.tinkoff.token or "").strip():
    errors.append("Tinkoff: не задан токен (TINKOFF_TOKEN / config)")
  aid = (cfg.tinkoff.account_id or "").strip()
  if not aid:
    errors.append("Tinkoff: пустой account_id — укажите TINKOFF_ACCOUNT_ID (после reset_sandbox подставьте новый id)")
  if not (cfg.telegram.token or "").strip():
    errors.append("Telegram: не задан токен бота (TELEGRAM_TOKEN)")
  if not cfg.telegram.admin_chat_id:
    errors.append("Telegram: admin_chat_id = 0 — уведомления и управление не дойдут (TELEGRAM_ADMIN_CHAT_ID)")
  dp = getattr(cfg, "dynamic_portfolio", None)
  dynamic_on = bool(dp and dp.enabled)
  if not cfg.instruments and not dynamic_on:
    errors.append("Нет инструментов в конфиге")
  if dynamic_on and dp and not dp.candidates and not cfg.instruments:
    errors.append("dynamic_portfolio.enabled: укажите candidates или instruments как fallback")
  if not dynamic_on:
    total_w = sum(getattr(i, "target_weight", 0) for i in cfg.instruments)
    if cfg.instruments and abs(total_w - 1.0) > 0.01:
      errors.append(f"Сумма target_weight должна быть ~1.0, получено {total_w:.2f}")
  for i in cfg.instruments:
    if not getattr(i, "figi", "").strip():
      errors.append(f"Инструмент без figi: {getattr(i, 'ticker', '')}")
    s = getattr(i, "strategy", None)
    strategies_to_check = [s] if isinstance(s, str) else (s if isinstance(s, list) else [])
    for strat in strategies_to_check:
      if strat is not None and strat not in VALID_STRATEGIES:
        errors.append(f"Неизвестная стратегия для {getattr(i, 'ticker', '')}: {strat}")
    if strategies_to_check and "rl" in strategies_to_check:
      params = getattr(i, "strategy_params", None) or {}
      if not params.get("rl_model_path"):
        errors.append(f"Для стратегии rl у инструмента {getattr(i, 'ticker', '')} укажите strategy_params.rl_model_path")
  try:
    from .learned_params import load_learned_params
    data = load_learned_params()
    if not isinstance(data, dict):
      errors.append("learned_params: неверный формат (ожидается dict)")
  except Exception as e:
    errors.append(f"learned_params: {e}")
  return len(errors) == 0, errors

