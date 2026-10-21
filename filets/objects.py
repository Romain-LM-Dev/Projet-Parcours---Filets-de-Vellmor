"""Stockage objet des fichiers bruts : les documents du corpus (sources du RAG, découpés et vectorisés dans pgvector) et
l'archive de chaque partie (`events.jsonl`, `indicators.jsonl`, `config.json`, `summary.json`).

`storage.objects.kind` :
- `none`  : rien de plus que le dossier `runs/` (par défaut) ;
- `local` : un dossier qui imite un magasin d'objets (clé = chemin relatif) ;
- `s3`    : un service compatible S3, en asynchrone (miniopy-async) : MinIO dans `docker-compose.yml`, ou
            AWS S3… Les clés d'accès viennent de `FILETS_S3_ACCESS_KEY` / `FILETS_S3_SECRET_KEY`, sinon de la configuration.

Clés : `corpus/<empreinte du corpus>/<fichier>.md`, `runs/<run_id>/<fichier>`.
"""
from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import os
from pathlib import Path

from .config import ROOT

log = logging.getLogger("filets.objects")

RUN_FILES = ("events.jsonl", "indicators.jsonl", "config.json", "summary.json")


def content_type(name: str) -> str:
    if name.endswith(".jsonl"):
        return "application/x-ndjson"
    if name.endswith(".md"):
        return "text/markdown; charset=utf-8"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class LocalObjects:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.where = str(self.root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"clé d'objet invalide : {key}")
        return p

    async def open(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)

    async def put_bytes(self, key: str, data: bytes, ctype: str | None = None) -> str:
        p = self._path(key)

        def write():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

        await asyncio.to_thread(write)
        return key

    async def get_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    async def list(self, prefix: str = "") -> list[str]:
        def walk():
            return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in self.root.rglob("*") if p.is_file())

        return [k for k in await asyncio.to_thread(walk) if k.startswith(prefix)]

    async def aclose(self) -> None:
        pass


class S3Objects:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, secure: bool = False,
                 region: str | None = None):
        from miniopy_async import Minio

        self.bucket = bucket
        self.where = f"{'https' if secure else 'http'}://{endpoint}/{bucket}"
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure, region=region)

    async def open(self) -> None:
        if not await self.client.bucket_exists(self.bucket):
            await self.client.make_bucket(self.bucket)

    async def put_bytes(self, key: str, data: bytes, ctype: str | None = None) -> str:
        await self.client.put_object(self.bucket, key, io.BytesIO(data), len(data),
                                     content_type=ctype or content_type(key))
        return key

    async def get_bytes(self, key: str) -> bytes:
        resp = await self.client.get_object(self.bucket, key)
        try:
            return await resp.read()
        finally:
            resp.release()

    async def exists(self, key: str) -> bool:
        from miniopy_async.error import S3Error

        try:
            await self.client.stat_object(self.bucket, key)
            return True
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return False
            raise

    async def list(self, prefix: str = "") -> list[str]:
        return sorted([o.object_name async for o in self.client.list_objects(self.bucket, prefix=prefix, recursive=True)])

    async def aclose(self) -> None:
        await self.client.close_session()


def make_objects(cfg: dict):
    """Le magasin d'objets de la configuration (`storage.objects`), ou None."""
    o = (cfg.get("storage") or {}).get("objects") or {}
    kind = o.get("kind", "none")
    if kind == "none":
        return None
    if kind == "local":
        return LocalObjects(ROOT / o.get("root", "data/objects"))
    if kind == "s3":
        return S3Objects(o["endpoint"], o["bucket"],
                         os.environ.get("FILETS_S3_ACCESS_KEY") or o.get("access_key", ""),
                         os.environ.get("FILETS_S3_SECRET_KEY") or o.get("secret_key", ""),
                         bool(o.get("secure", False)), o.get("region"))
    raise ValueError(f"stockage objet inconnu : {kind} (none, local ou s3)")


async def archive_run(objects, run_dir: Path, run_id: str) -> list[str]:
    """Dépose les fichiers d'une partie dans le magasin d'objets ; renvoie les clés écrites."""
    keys = []
    for name in RUN_FILES:
        path = Path(run_dir) / name
        if path.exists():
            data = await asyncio.to_thread(path.read_bytes)
            keys.append(await objects.put_bytes(f"runs/{run_id}/{name}", data, content_type(name)))
    return keys
