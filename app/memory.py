"""Chat memory. Every read and write is scoped to (tenant, owner) so a conversation id alone exposes nothing."""
from app.db import q


def load_history(p: dict, conversation_id: str, turns: int) -> list[dict]:
    rows = q("""select role, content from chat_messages
                where tenant_id = %s and owner_sub = %s and conversation_id = %s
                order by id desc limit %s""", (p["tenant"], p["sub"], conversation_id, turns * 2))
    return rows[::-1]


def save_turn(p: dict, conversation_id: str, question: str, answer: str) -> None:
    q("""insert into chat_messages (tenant_id, owner_sub, conversation_id, role, content)
         values (%s, %s, %s, 'user', %s), (%s, %s, %s, 'assistant', %s)""",
      (p["tenant"], p["sub"], conversation_id, question, p["tenant"], p["sub"], conversation_id, answer))


def list_messages(p: dict, conversation_id: str) -> list[dict]:
    return q("""select role, content, created_at from chat_messages
                where tenant_id = %s and owner_sub = %s and conversation_id = %s order by id limit 100""",
             (p["tenant"], p["sub"], conversation_id))
