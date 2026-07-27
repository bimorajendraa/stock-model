from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.database.base import Base
from src.database.models.company import Company, CompanyAlias, SectorRegistry
from src.ingestion.company_aliases import import_company_aliases


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[SectorRegistry.__table__, Company.__table__, CompanyAlias.__table__],
    )
    with Session(engine) as db:
        now = dt.datetime.now(dt.UTC)
        db.add(
            Company(
                ticker="BBCA",
                company_name="PT Bank Central Asia Tbk",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        yield db


def test_import_company_aliases_is_idempotent_and_updates_metadata(session, tmp_path):
    path = tmp_path / "aliases.csv"
    path.write_text(
        "ticker,previous_ticker,previous_name,effective_from,effective_to,reason\n"
        "BBCA,BBCAO,Bank Central Asia,2000-05-31,2020-12-31,official history\n",
        encoding="utf-8",
    )

    first = import_company_aliases(session, path)
    now = dt.datetime.now(dt.UTC)
    for alias in session.new:
        if isinstance(alias, CompanyAlias):
            alias.created_at = now
            alias.updated_at = now
    session.commit()
    second = import_company_aliases(session, path)

    assert (first.rows_seen, first.created, first.updated) == (1, 1, 0)
    assert (second.rows_seen, second.created, second.updated) == (1, 0, 0)
    alias = session.scalar(select(CompanyAlias))
    assert alias is not None
    assert alias.previous_ticker == "BBCAO"
    assert alias.effective_to == dt.date(2020, 12, 31)


@pytest.mark.parametrize(
    "data, message",
    [
        ("ticker,effective_from,previous_name\nNOPE,2020-01-01,Old Name\n", "unknown current"),
        ("ticker,effective_from,previous_name\nBBCA,bad-date,Old Name\n", "ISO date"),
        ("ticker,effective_from,previous_name\nBBCA,2020-01-01,\n", "previous_ticker or previous_name"),
    ],
)
def test_import_company_aliases_rejects_invalid_rows(session, tmp_path, data, message):
    path = tmp_path / "aliases.csv"
    path.write_text(data, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        import_company_aliases(session, path)
