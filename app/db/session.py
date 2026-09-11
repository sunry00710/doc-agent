import sqlite3
from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 5} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            autocommit = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL：允许 uvicorn 与独立 worker 并发读写，缓解「database is locked」。
            # busy_timeout 让写锁竞争时等待而非立即失败。内存库（sqlite://）不支持 WAL，跳过。
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
            dbapi_connection.autocommit = autocommit

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
