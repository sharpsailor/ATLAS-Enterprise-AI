import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings


# ponytail: one connection per query; switch to psycopg_pool.ConnectionPool if latency matters
def q(sql: str, params=(), one: bool = False):
    with psycopg.connect(settings.database_url, row_factory=dict_row, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
    return (rows[0] if rows else None) if one else rows


def audit(actor: str, tenant_id: str, action: str, **detail) -> None:
    q("insert into audit_events (actor, tenant_id, action, detail) values (%s, %s, %s, %s)",
      (actor, tenant_id, action, Jsonb(detail)))
