"""Check the local LLM (Ollama) works: chat + embeddings. Run: python test/test.py"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM = os.getenv("LLM_MODEL", "llama3.2")
EMBED = os.getenv("EMBED_MODEL", "mxbai-embed-large")


def test_chat():
    r = httpx.post(f"{URL}/api/chat", timeout=120, json={
        "model": LLM, "stream": False,
        "messages": [{"role": "user", "content": "What is 2+2? Reply with only the number."}],
    })
    r.raise_for_status()
    answer = r.json()["message"]["content"]
    assert "4" in answer, f"unexpected answer: {answer!r}"
    print(f"chat ok  ({LLM}): {answer.strip()}")


def test_embed():
    r = httpx.post(f"{URL}/api/embed", timeout=120, json={"model": EMBED, "input": "hello"})
    r.raise_for_status()
    dims = len(r.json()["embeddings"][0])
    assert dims == 1024, f"{EMBED} gave {dims} dims; Pinecone index expects 1024"
    print(f"embed ok ({EMBED}): {dims} dims")


if __name__ == "__main__":
    test_chat()
    test_embed()
