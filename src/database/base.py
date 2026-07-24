"""Declarative base shared by every ORM model.

Importing this module (directly or transitively via src.database.models)
populates ``Base.metadata`` -- this is what Alembic's env.py points
``target_metadata`` at for autogeneration.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
