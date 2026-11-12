"""Create the Atlas tables. Run from repo root: python scripts/init_db.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import q  # noqa: E402

q((ROOT / "infra/schema.sql").read_text())
tables = q("select table_name from information_schema.tables where table_schema = 'public' order by 1")
print("tables:", ", ".join(t["table_name"] for t in tables))
