"""Types de colonnes portables — Postgres en prod, SQLite pour les tests.

- `GUID`  : UUID natif sous Postgres, CHAR(32) ailleurs.
- `JSONB` : JSONB sous Postgres, JSON ailleurs.
"""
from __future__ import annotations

import uuid

from sqlalchemy import CHAR, JSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return uuid.UUID(str(value)).hex if not isinstance(value, uuid.UUID) else value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


JSONB = JSON().with_variant(PG_JSONB(), "postgresql")
