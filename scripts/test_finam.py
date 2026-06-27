from finam_client import FinamClient

c = FinamClient()
print("configured:", c.configured)
try:
    bars = c.get_daily_bars("SBER", 30)
    print("bars:", len(bars))
    if bars:
        print("last_close:", bars[-1]["close"])
except Exception as e:
    print("error:", e)
