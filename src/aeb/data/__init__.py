"""Generic, backend-swappable data layer.

Document-shaped entities + an abstract Repository so the storage backend is
interchangeable: SQLite locally now, Cosmos DB (or anything document-oriented)
later, with no change to the pipeline. Every entity carries an `id` and a
`partition_key` (question_id) so it maps cleanly onto Cosmos partitioning.
"""
from .entities import (  # noqa: F401
    BinDesign, ModelRun, Question, Resolution, SurfacedPrediction,
)
from .repository import Repository  # noqa: F401
from .sqlite_repo import SqliteRepository  # noqa: F401
