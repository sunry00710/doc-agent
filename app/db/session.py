import sqlite3
from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SQLITE_BUSY_TIMEOUT_MS = 15000


def create_database_engine(database_url: str, *, immediate_transactions: bool = False) -> Engine:
    """Create an engine for the given URL.

    ``immediate_transactions``（仅 SQLite 生效）让每个事务以 ``BEGIN IMMEDIATE`` 开始。
    API 侧写操作普遍是「先读校验、再写更新」，WAL 模式下这类延迟事务只要在读写之间
    有别的连接提交，就会立刻抛 SQLITE_BUSY_SNAPSHOT（busy_timeout 对写升级无效）。
    显式 IMMEDIATE 让写事务在开始时排队，从根上消除这类「database is locked」。
    worker 侧事务可能较长（入库 + 建索引），保持默认延迟事务 + 既有重试策略。
    """
    is_sqlite = database_url.startswith("sqlite")
    connect_args = (
        {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}
        if is_sqlite
        else {}
    )
    engine = create_engine(database_url, connect_args=connect_args)
    if not is_sqlite:
        return engine

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        if immediate_transactions:
            # 关闭 pysqlite 的隐式 BEGIN：事务改由下面的 "begin" 事件显式发起。
            dbapi_connection.isolation_level = None
        else:
            autocommit = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL：允许 uvicorn 与独立 worker 并发读写。内存库（sqlite://）不支持 WAL，跳过。
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()
        if not immediate_transactions:
            dbapi_connection.autocommit = autocommit

    if immediate_transactions:

        @event.listens_for(engine, "begin")
        def begin_immediate(connection) -> None:
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
