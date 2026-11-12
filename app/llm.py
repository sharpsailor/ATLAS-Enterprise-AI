"""LLM + embeddings, standing in for Bedrock. Gemini when GEMINI_API_KEY is set (hosted), else local Ollama."""
import re
import time

import httpx

from app.config import settings
from app.observability import trace

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# mxbai-embed-large wants this prefix on queries (not on documents) for retrieval.
OLLAMA_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def chat_model_name() -> str:
    return settings.gemini_chat_model if settings.gemini_api_key else settings.llm_model


def embed_model_name() -> str:
    return settings.gemini_embed_model if settings.gemini_api_key else settings.embed_model


def _retry_delay(r: httpx.Response, attempt: int) -> float:
    """Seconds Gemini asks us to wait (RetryInfo.retryDelay, e.g. "17s"), else exponential backoff."""
    try:
        for d in r.json()["error"]["details"]:
            if d.get("@type", "").endswith("RetryInfo") and (m := re.match(r"([\d.]+)s", d.get("retryDelay", ""))):
                return float(m.group(1))
    except (ValueError, KeyError, TypeError):
        pass
    return 2.0 ** attempt


def _gemini(method: str, body: dict, attempts: int = 4, max_wait: float = 30.0) -> dict:
    # The free tier limits requests per minute; waiting out a 429 beats failing a whole upload.
    for attempt in range(attempts):
        r = httpx.post(f"{GEMINI_URL}/{method}", json=body, timeout=120,
                       headers={"x-goog-api-key": settings.gemini_api_key})
        if r.status_code not in (429, 503) or attempt == attempts - 1:
            break
        time.sleep(min(_retry_delay(r, attempt), max_wait))
    r.raise_for_status()
    return r.json()


def _ollama(path: str, body: dict) -> dict:
    r = httpx.post(f"{settings.ollama_url}/api/{path}", json=body, timeout=300)
    r.raise_for_status()
    return r.json()


@trace("embed")
def embed(texts: list[str], query: bool = False) -> list[list[float]]:
    if settings.gemini_api_key:
        model = settings.gemini_embed_model
        vectors = [e["values"] for e in _gemini(f"{model}:batchEmbedContents", {"requests": [
            {"model": f"models/{model}", "content": {"parts": [{"text": t}]},
             # Top-level on purpose: the REST API silently ignores these inside embedContentConfig (tested live).
             "taskType": "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
             "outputDimensionality": settings.embed_dim} for t in texts]})["embeddings"]]
    else:
        if query:
            texts = [OLLAMA_QUERY_PREFIX + t for t in texts]
        vectors = _ollama("embed", {"model": settings.embed_model, "input": texts})["embeddings"]
    if vectors and len(vectors[0]) != settings.embed_dim:
        raise ValueError(f"embedding has {len(vectors[0])} dims, index expects {settings.embed_dim}")
    return vectors


@trace("answer")
def answer(system: str, messages: list[dict]) -> str:
    if settings.gemini_api_key:
        data = _gemini(f"{settings.gemini_chat_model}:generateContent", {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                         for m in messages],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 750},
        })
        # A safety block returns a candidate without content.
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip() or "No answer was generated for this question."
    return _ollama("chat", {
        "model": settings.llm_model, "stream": False,
        "messages": [{"role": "system", "content": system}, *messages],
        "options": {"temperature": 0.1, "num_predict": 750},
    })["message"]["content"].strip()
