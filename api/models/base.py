"""
SQLAlchemy declarative base and shared mixins.

All ORM models inherit from Base (gives them the metadata registry)
and the mixins (UUID PK + created_at timestamp).

Why server_default=func.now() instead of default=datetime.utcnow:
  - server_default runs on the DB side — consistent even if app servers
    have clock skew across multiple pods.
  - Python-side default=datetime.utcnow runs before the INSERT,
    so it reflects the app clock, not the DB clock.
"""

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    DeclarativeBase (SQLAlchemy 2.0) replaces the old declarative_base()
    function. Gives us typed Mapped[] columns with IDE autocomplete.
    """
    pass


class UUIDPrimaryKeyMixin:
    """
    UUID primary key, generated in Python before the INSERT.

    Why Python-side (default=uuid.uuid4) not server-side (gen_random_uuid()):
      - Python knows the ID immediately after object creation, before commit.
      - Lets us reference the ID in related objects in the same transaction.
      - No extra DB round-trip to retrieve the generated ID.
    """
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class TimestampMixin:
    """
    Adds created_at to any model that needs it.
    Mixin — no table of its own, just injects the column.
    """
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
