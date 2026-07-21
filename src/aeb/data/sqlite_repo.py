"""SQLite backend for the generic Repository.

Each collection is a table `(id PK, pk, doc JSON)`. Documents are stored whole
as JSON so the schema is flexible and mirrors a document store; the `pk` column
(partition key) is kept separate and indexed for Cosmos-parity and fast scoping.
Equality queries filter in Python so behaviour matches any document backend.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .repository import Repository


class SqliteRepository(Repository):
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")  # tolerate concurrent writers
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._tables: set[str] = set()

    def _ensure(self, collection: str) -> None:
        if collection not in self._tables:
            self.conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{collection}" '
                f"(id TEXT PRIMARY KEY, pk TEXT, doc TEXT)")
            self.conn.execute(
                f'CREATE INDEX IF NOT EXISTS "{collection}_pk" ON "{collection}" (pk)')
            self.conn.commit()
            self._tables.add(collection)

    def upsert(self, collection: str, doc: dict[str, Any]) -> None:
        self._ensure(collection)
        self.conn.execute(
            f'INSERT INTO "{collection}" (id, pk, doc) VALUES (?, ?, ?) '
            f"ON CONFLICT(id) DO UPDATE SET pk=excluded.pk, doc=excluded.doc",
            (doc["id"], doc.get("_pk"), json.dumps(doc)))
        self.conn.commit()

    def get(self, collection: str, id: str) -> dict[str, Any] | None:
        self._ensure(collection)
        row = self.conn.execute(
            f'SELECT doc FROM "{collection}" WHERE id=?', (id,)).fetchone()
        return json.loads(row["doc"]) if row else None

    def all(self, collection: str) -> list[dict[str, Any]]:
        self._ensure(collection)
        return [json.loads(r["doc"])
                for r in self.conn.execute(f'SELECT doc FROM "{collection}"').fetchall()]

    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]:
        return [d for d in self.all(collection)
                if all(d.get(k) == v for k, v in equals.items())]

    def delete(self, collection: str, id: str) -> None:
        self._ensure(collection)
        self.conn.execute(f'DELETE FROM "{collection}" WHERE id=?', (id,))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
