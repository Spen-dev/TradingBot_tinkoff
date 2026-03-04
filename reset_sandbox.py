"""Удаление всех sandbox-счётов и очистка позиций/сделок в песочнице."""
import os

from dotenv import load_dotenv
from tinkoff.invest.sandbox.client import SandboxClient


def main() -> None:
  load_dotenv()
  token = os.getenv("TINKOFF_TOKEN")
  if not token:
    raise SystemExit("TINKOFF_TOKEN не задан в .env")

  with SandboxClient(token) as client:
    resp = client.sandbox.get_sandbox_accounts()
    accounts = list(resp.accounts or [])
    if not accounts:
      print("Sandbox accounts: <none>")
      return

    print("Sandbox accounts to reset/close:")
    for acc in accounts:
      print(f"- {acc.id} ({acc.name})")

    for acc in accounts:
      aid = acc.id
      try:
        client.sandbox.clear_sandbox_account(account_id=aid)
      except Exception as e:
        print(f"clear_sandbox_account failed for {aid}: {e}")
      try:
        client.sandbox.close_sandbox_account(account_id=aid)
      except Exception as e:
        print(f"close_sandbox_account failed for {aid}: {e}")
      else:
        print(f"Closed sandbox account {aid}")


if __name__ == "__main__":
  main()

