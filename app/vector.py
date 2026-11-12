from functools import cache

from pinecone import Pinecone

from app.config import settings
from app.observability import trace


@cache
def index():
    return Pinecone(api_key=settings.pinecone_api_key).Index(host=settings.pinecone_index_host)


def namespace(tenant_id: str) -> str:
    return f"tenant-{tenant_id}"


@trace("upsert")
def upsert(tenant_id: str, vectors: list[dict]) -> None:
    for i in range(0, len(vectors), 50):
        index().upsert(vectors=vectors[i:i + 50], namespace=namespace(tenant_id))


@trace("search")
def search(tenant_id: str, vector: list[float], principal: dict, top_k: int = 5) -> list[dict]:
    acl = {"$or": [{"allowed_groups": {"$in": principal["groups"]}},
                   {"owner_sub": {"$eq": principal["sub"]}}]}
    res = index().query(namespace=namespace(tenant_id), vector=vector, top_k=top_k,
                        include_metadata=True, filter=acl)
    return [{"score": m.score, **m.metadata} for m in res.matches]
