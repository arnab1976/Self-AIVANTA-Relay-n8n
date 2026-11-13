"""Project-scoped hybrid retrieval (keyword + vector).

Default embedder is a deterministic hashing vectorizer so the system runs
without an embedding API. Set EMBEDDINGS_PROVIDER=openai to use OpenAI
embeddings; on PostgreSQL the chunk vectors can be moved to a pgvector column
(see docs/architecture/data-contracts.md).
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter

DIM = 256
TOKEN = re.compile(r"[a-z0-9]{2,}")


def chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def _hash_embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for tok in TOKEN.findall(text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def embed(texts: list[str]) -> list[list[float]]:
    if os.getenv("EMBEDDINGS_PROVIDER", "hash") == "openai":
        import httpx
        resp = httpx.post("https://api.openai.com/v1/embeddings", timeout=60,
                          headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                          json={"model": os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-small"), "input": texts})
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]
    return [_hash_embed(t) for t in texts]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def hybrid_search(query: str, chunks: list[dict], top_k: int = 6, alpha: float = 0.5) -> list[dict]:
    """chunks: [{"id", "text", "embedding", "source"}] already filtered to tenant + project."""
    if not chunks:
        return []
    qv = embed([query])[0]
    qt = Counter(TOKEN.findall(query.lower()))
    scored = []
    for c in chunks:
        ct = Counter(TOKEN.findall(c["text"].lower()))
        kw = sum(min(qt[t], ct[t]) for t in qt) / (sum(qt.values()) or 1)
        vec = _cos(qv, c["embedding"]) if c.get("embedding") and len(c["embedding"]) == len(qv) else 0.0
        scored.append((alpha * kw + (1 - alpha) * vec, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**c, "score": round(s, 4)} for s, c in scored[:top_k]]
