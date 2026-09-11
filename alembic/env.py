from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import Settings
from app.db.base import Base
from app.documents import models as document_models  # noqa: F401
from app.identity import models  # noqa: F401
from app.jobs import models as job_models  # noqa: F401
from app.knowledge import models as knowledge_models  # noqa: F401
from app.knowledge import promotion as promotion_models  # noqa: F401
from app.projects import models as project_models  # noqa: F401
from app.quality import models as quality_models  # noqa: F401
from app.reviews import models as review_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

configured_url = config.get_main_option("sqlalchemy.url")
default_url = "sqlite:///./doc_agent.db"
if not configured_url or configured_url == default_url:
    configured_url = Settings().database_url
config.set_main_option("sqlalchemy.url", configured_url.replace("%", "%%"))
target_metadata = Base.metadata

# SQLite FTS5 虚拟表与影子表由 0005 迁移的原生 SQL 创建，不在 SQLAlchemy 元数据里；
# 若不排除，autogenerate 会把它们误判成「需要删除的表」。
FTS_TABLE_PREFIX = "knowledge_chunks_fts"


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    if type_ == "table" and name is not None and name.startswith(FTS_TABLE_PREFIX):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
