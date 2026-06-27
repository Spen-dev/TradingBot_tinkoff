from tinkoff_bot.finam_client import FinamClient
from tinkoff_bot.finam_advisor import select_portfolio_via_finam

c = FinamClient()
candidates = ["SBER", "LKOH", "GMKN", "PLZL", "MGNT", "TATN"]
sel, msg = select_portfolio_via_finam(c, candidates, 4, 6, 0.3, history_days=60)
print("selections:", len(sel))
print("msg:", msg)
for s in sel:
    print(s["ticker"], s["target_weight"])
