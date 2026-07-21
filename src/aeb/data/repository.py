"""Abstract repository — the seam that makes the storage backend swappable.

Deliberately document-oriented (upsert/get/query/all/delete over dicts) so a
Cosmos DB backend drops in behind the same interface. Analytics is computed in
Python over retrieved documents (not backend-specific SQL) to stay portable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .entities import Entity


class Repository(ABC):
    @abstractmethod
    def upsert(self, collection: str, doc: dict[str, Any]) -> None: ...

    @abstractmethod
    def get(self, collection: str, id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def all(self, collection: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def query(self, collection: str, **equals: Any) -> list[dict[str, Any]]: ...

    @abstractmethod
    def delete(self, collection: str, id: str) -> None: ...

    def close(self) -> None:  # optional for backends that hold connections
        pass

    # -- typed convenience over entities -----------------------------------
    def save(self, entity: Entity) -> None:
        self.upsert(entity.COLLECTION, entity.to_doc())

    def load(self, cls: type[Entity], id: str) -> Entity | None:
        doc = self.get(cls.COLLECTION, id)
        return cls.from_doc(doc) if doc else None

    def load_all(self, cls: type[Entity], **equals: Any) -> list[Entity]:
        docs = self.query(cls.COLLECTION, **equals) if equals else self.all(cls.COLLECTION)
        return [cls.from_doc(d) for d in docs]
