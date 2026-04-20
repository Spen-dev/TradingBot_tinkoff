"""Скрипт резервного копирования каталогов data/ и learned_params/."""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LEARNED_DIR = ROOT / "learned_params"


def main() -> None:
  stamp = datetime.now().strftime("%Y%m%d_%H%M")
  out = ROOT / f"backup_{stamp}.zip"
  with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for folder in (DATA_DIR, LEARNED_DIR):
      if not folder.exists():
        continue
      for f in folder.rglob("*"):
        if f.is_file():
          zf.write(f, f.relative_to(ROOT))
  print(f"Создан архив: {out}")


if __name__ == "__main__":
  main()
