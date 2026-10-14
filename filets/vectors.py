"""Vecteurs de la récupération (RAG) : plongements et magasin PostgreSQL + pgvector.

Avec `rag.backend: pgvector`, les passages du corpus et les souvenirs des agents sont rangés dans PostgreSQL avec leur
vecteur (pgvector), et la recherche se fait dans la base : similarité cosinus, et dans la même requête les droits de
l'agent (son hameau, rien de postérieur à son horizon d'information, C6). Les textes bruts du corpus vont au stockage
objet (`objects.py`).

Plongements (`rag.embeddings`) :
- `ollama` : `POST /api/embed` d'Ollama (ex. `embeddinggemma`, multilingue, 768 dimensions), par lots, avec un cache par
  texte : la même parole entendue par huit pêcheurs n'est calculée qu'une fois ;
- `hash` : sac de mots haché, sans modèle, déterministe et gratuit (tests, ou base sans modèle de plongement) ; sa
  similarité cosinus mesure le recouvrement des mots, pas le sens.

Une table par dimension (`rag_chunks_768`…), et chaque ligne porte le nom du modèle qui l'a calculée : deux modèles ne se
mélangent jamais.
"""
from __future__ import annotations

import asyncio
import math
import os
import zlib
from collections import Counter, OrderedDict

import httpx

from .rag import tokenize


class EmbeddingError(RuntimeError):
    pass


class HashEmbedder:
    """Sac de mots haché : mêmes mots que BM25 (minuscules, sans accents, sans mots vides, racinisés), poids 1 + log(tf)."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hash-{dim}"

    def vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for i, n in Counter(zlib.crc32(t.encode()) % self.dim for t in tokenize(text)).items():
            v[i] = 1.0 + math.log(n)
        norm = math.sqrt(sum(x * x for x in v))
        if not norm:                     # texte sans mot porteur : un vecteur non nul, pour que le cosinus soit défini
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(t) for t in texts]

    async def aclose(self) -> None:
        pass


class OllamaEmbedder:
    """Plongements d'un modèle Ollama. `cpu` : le calculer sur le processeur, pour laisser la carte graphique aux modèles
    de langage (un modèle de plongement de 300 M paramètres y reste rapide pour des phrases courtes)."""

    def __init__(self, base_url: str, model: str, dim: int, cpu: bool = True, timeout_s: float = 120.0, batch: int = 32,
                 cache_max: int = 50_000):
        root = base_url.rstrip("/")
        root = root[:-3] if root.endswith("/v1") else root
        self.url = f"{root}/api/embed"
        self.model, self.dim, self.name = model, dim, f"ollama:{model}"
        self.options = {"num_gpu": 0} if cpu else {}
        self.batch, self.cache_max = batch, cache_max
        self.cache: OrderedDict[str, list[float]] = OrderedDict()
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=3.0))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        todo = [t for t in dict.fromkeys(texts) if t not in self.cache]
        got: dict[str, list[float]] = {}
        for i in range(0, len(todo), self.batch):
            part = todo[i:i + self.batch]
            body = {"model": self.model, "input": part, "keep_alive": "30m", "truncate": True}
            if self.options:
                body["options"] = self.options
            try:
                r = await self.http.post(self.url, json=body)
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"Ollama ne répond pas ({exc or type(exc).__name__})") from None
            if r.status_code != 200:
                raise EmbeddingError(f"Ollama /api/embed : HTTP {r.status_code} {r.text[:160]}")
            vecs = r.json().get("embeddings") or []
            if len(vecs) != len(part) or any(len(v) != self.dim for v in vecs):
                raise EmbeddingError(f"{self.model} ne rend pas {len(part)} vecteurs de {self.dim} dimensions "
                                     f"(reçu {len(vecs)} × {len(vecs[0]) if vecs else 0})")
            got.update(zip(part, vecs))
        for t, v in got.items():
            self.cache[t] = v
        while len(self.cache) > self.cache_max:
            self.cache.popitem(last=False)
        return [got[t] if t in got else self.cache[t] for t in texts]

    async def aclose(self) -> None:
        await self.http.aclose()


def make_embedder(rag_cfg: dict):
    e = rag_cfg.get("embeddings") or {}
    kind = e.get("kind", "hash")
    if kind == "hash":
        return HashEmbedder(int(e.get("dim", 384)))
    if kind == "ollama":
        return OllamaEmbedder(e.get("base_url", "http://localhost:11434"), e["model"], int(e["dim"]), bool(e.get("cpu", True)),
                              float(e.get("timeout_s", 120)), int(e.get("batch", 32)))
    raise ValueError(f"plongements inconnus : {kind} (hash ou ollama)")


def postgres_dsn(cfg: dict) -> str:
    """L'adresse de la base : la variable d'environnement `FILETS_PG_DSN` l'emporte sur la configuration."""
    return os.environ.get("FILETS_PG_DSN") or cfg["storage"]["postgres"]["dsn"]


async def connect_pool(dsn: str, vector: bool = True, timeout: float = 5.0):
    """Pool asyncpg. Avec `vector`, l'extension pgvector est créée si besoin et son type est connu de chaque connexion."""
    import asyncpg

    if vector:
        from pgvector.asyncpg import register_vector

        conn = await asyncpg.connect(dsn, timeout=timeout)
        try:
            await conn.execute("SELECT pg_advisory_lock(7310); CREATE EXTENSION IF NOT EXISTS vector; "
                               "SELECT pg_advisory_unlock(7310);")
        finally:
            await conn.close()
        return await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=register_vector, timeout=timeout)
    return await asyncpg.create_pool(dsn, min_size=1, max_size=4, timeout=timeout)


class PgVectorStore:
    """Passages du corpus et souvenirs des agents, avec leur vecteur, dans PostgreSQL + pgvector."""

    def __init__(self, dsn: str, embedder):
        self.dsn, self.embedder = dsn, embedder
        self.dim, self.model = embedder.dim, embedder.name
        self.chunks, self.memories = f"rag_chunks_{self.dim}", f"rag_memories_{self.dim}"
        self.pool = None

    async def open(self) -> None:
        self.pool = await connect_pool(self.dsn)
        d, c, m = self.dim, self.chunks, self.memories
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(7311)")      # deux processus qui démarrent ensemble
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {c} (
                      embedder text NOT NULL, corpus text NOT NULL, id text NOT NULL, title text, body text NOT NULL,
                      visible_to text[] NOT NULL, sim_time double precision NOT NULL, object_key text,
                      embedding vector({d}) NOT NULL, PRIMARY KEY (embedder, corpus, id));
                    CREATE INDEX IF NOT EXISTS {c}_hnsw ON {c} USING hnsw (embedding vector_cosine_ops);
                    CREATE TABLE IF NOT EXISTS {m} (
                      run_id text NOT NULL, id text NOT NULL, owner text NOT NULL, t double precision NOT NULL,
                      body text NOT NULL, kind text, importance double precision, pinned boolean, expires_season integer,
                      source_event_id text, event_id text, embedder text NOT NULL, embedding vector({d}) NOT NULL,
                      PRIMARY KEY (run_id, id));
                    CREATE INDEX IF NOT EXISTS {m}_owner ON {m} (run_id, owner, t);
                    CREATE INDEX IF NOT EXISTS {m}_hnsw ON {m} USING hnsw (embedding vector_cosine_ops);""")

    async def aclose(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    # ------------------------------------------------------------ corpus
    async def count_chunks(self, corpus: str) -> int:
        return await self.pool.fetchval(f"SELECT count(*) FROM {self.chunks} WHERE embedder = $1 AND corpus = $2",
                                        self.model, corpus)

    async def put_chunks(self, corpus: str, rows: list[tuple]) -> None:
        """`rows` : (id, titre, texte, visible_to, sim_time, clé objet, vecteur)."""
        await self.pool.executemany(
            f"INSERT INTO {self.chunks} (embedder, corpus, id, title, body, visible_to, sim_time, object_key, embedding) "
            f"VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT (embedder, corpus, id) DO UPDATE SET "
            f"title = EXCLUDED.title, body = EXCLUDED.body, visible_to = EXCLUDED.visible_to, "
            f"sim_time = EXCLUDED.sim_time, object_key = EXCLUDED.object_key, embedding = EXCLUDED.embedding",
            [(self.model, corpus, *r) for r in rows])

    async def search_chunks(self, corpus: str, qvec, hamlet: str, horizon: float, k: int, min_score: float = 0.0):
        return await self.pool.fetch(
            f"SELECT id, 1 - (embedding <=> $3) AS score FROM {self.chunks} "
            f"WHERE embedder = $1 AND corpus = $2 AND sim_time <= $4 AND ('all' = ANY(visible_to) OR $5 = ANY(visible_to)) "
            f"AND 1 - (embedding <=> $3) > $6 ORDER BY embedding <=> $3, id LIMIT $7",
            self.model, corpus, qvec, horizon, hamlet, min_score, k)

    # ------------------------------------------------------------ souvenirs
    async def put_memories(self, run_id: str, rows: list[tuple]) -> None:
        """`rows` : (propriétaire, souvenir `memory.Memory`, vecteur)."""
        await self.pool.executemany(
            f"INSERT INTO {self.memories} (run_id, id, owner, t, body, kind, importance, pinned, expires_season, "
            f"source_event_id, event_id, embedder, embedding) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
            f"ON CONFLICT (run_id, id) DO NOTHING",
            [(run_id, m.id, owner, m.t, m.text, m.kind, m.importance, m.pinned, m.expires_season, m.source_event_id,
              m.event_id, self.model, vec) for owner, m, vec in rows])

    async def search_memories(self, run_id: str, owner: str, qvec, horizon: float, exclude: list[str], weights: dict,
                              decay: float, k: int):
        """Même score que `memory.MemoryStore.retrieve` (récence + importance + pertinence rapportée à la meilleure), mais la
        pertinence est la similarité cosinus des vecteurs, et tout est calculé par la base."""
        return await self.pool.fetch(
            f"""WITH c AS (
                  SELECT id, t, importance, greatest(1 - (embedding <=> $4), 0) AS rel FROM {self.memories}
                  WHERE run_id = $1 AND owner = $2 AND embedder = $3 AND t <= $5::float8 AND NOT (id = ANY($6::text[])))
                SELECT id, $7::float8 * exp(-($8::float8) * greatest(0, $5::float8 - t)) + $9::float8 * importance
                           + $10::float8 * coalesce(rel / nullif(max(rel) OVER (), 0), 0) AS score
                FROM c ORDER BY score DESC, id LIMIT $11""",
            run_id, owner, self.model, qvec, horizon, list(exclude), float(weights["recency"]), float(decay),
            float(weights["importance"]), float(weights["relevance"]), k)

    async def run_memories(self, run_id: str, query_vec, k: int, owner: str | None = None, horizon: float | None = None):
        """Recherche dans la mémoire collective d'une partie (tous les agents, ou un seul) : pour l'analyse et l'API."""
        return await self.pool.fetch(
            f"SELECT id, owner, t, body, kind, importance, event_id, 1 - (embedding <=> $3) AS score FROM {self.memories} "
            f"WHERE run_id = $1 AND embedder = $2 AND ($4::text IS NULL OR owner = $4) "
            f"AND ($5::double precision IS NULL OR t <= $5) ORDER BY embedding <=> $3, id LIMIT $6",
            run_id, self.model, query_vec, owner, horizon, k)


async def wait_for_postgres(dsn: str, timeout_s: float = 30.0) -> None:
    """Attend que la base accepte les connexions (conteneur qui démarre)."""
    import asyncpg

    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            conn = await asyncpg.connect(dsn, timeout=3.0)
            await conn.close()
            return
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.5)
