import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.config import DATA_DIR


DATABASE_PATH = DATA_DIR / "quantagent.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},
)


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(
    dbapi_connection: object,
    _connection_record: object,
) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
