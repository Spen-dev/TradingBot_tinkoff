import os

from tinkoff.invest import Client
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("TINKOFF_TOKEN")


def main() -> None:
  if not TOKEN:
    raise RuntimeError("TINKOFF_TOKEN is not set in environment or .env file")

  with Client(TOKEN) as client:
    print("Regular accounts:")
    regular = client.users.get_accounts()
    if regular.accounts:
      for acc in regular.accounts:
        print(f"- {acc.id}  ({acc.name})")
    else:
      print("- <none>")

    print("\nSandbox accounts:")
    sand = client.sandbox.users.get_accounts()
    if sand.accounts:
      for acc in sand.accounts:
        print(f"- {acc.id}  ({acc.name})")
    else:
      print("- <none>")

    if not sand.accounts:
      opened = client.sandbox.open_sandbox_account()
      print("\nOpened new sandbox account:")
      print(f"- {opened.account_id}")


if __name__ == "__main__":
  main()

