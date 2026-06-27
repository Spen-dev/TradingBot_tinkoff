from tinkoff_bot.finam_client import FinamClient
from tinkoff_bot.finam_advisor import score_bars

c = FinamClient()
for t in ["SBER", "LKOH", "GMKN"]:
    try:
        bars = c.get_daily_bars(t, 60)
        m = score_bars(bars)
        print(t, "bars", len(bars), "score", m["score"])
    except Exception as e:
        print(t, "ERR", e)
