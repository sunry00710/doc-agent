"""导入黑曜石库中爬取的政府官方审计公告，作为同一文档的三个年度版本。

来源：D:/Obsidian/Workspace1/10-历史报告-clean/（公开的审计署公告）
规范化处理：
- 去除 PDF 爬取产生的硬换行与多余空白（中文公文无词间空格，可安全整体拼接）
- 重建标题层级：文档标题 → #，"一、违反财经纪律…/二、行政事业性国有资产管理…" → ##，
  "（一）小节标题。" → ###，使知识库分块携带 heading_path
幂等：按文档标题跳过已导入的版本。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python scripts/<name>.py` 直接运行（补齐项目根到模块搜索路径）
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import create_database_engine
from app.documents.models import Document, DocumentVersion
from app.documents.service import create_document, create_version
from app.documents.storage import FileStorage
from app.identity.models import Role, User
from app.projects.models import Project
from app.projects.service import create_project

VAULT = Path(r"D:\Obsidian\Workspace1\10-历史报告-clean")
PROJECT_NAME = "演示项目：年度审计报告"
DOCUMENT_TITLE = "中央部门单位预算执行审计结果公告（2023-2025年度）"

# 按年度顺序导入：v1=2023年度、v2=2024年度、v3=2025年度
SOURCES = [
    "2024-01-2023年度预算执行审计结果.md",
    "2025-01-2024年度预算执行审计结果.md",
    "2026-01-2025年度预算执行审计结果.md",
]

_L1_SECTIONS = [
    "一、违反财经纪律等行为仍有发生",
    "二、行政事业性国有资产管理不够严格高效",
]


def normalize(raw: str) -> str:
    # 公文无词间空格：整体去除爬取产生的换行与空白
    text = re.sub(r"\s+", "", raw)
    # 文档标题
    text = re.sub(
        r"^(中央部门单位\d{4}年度预算执行等情况审计结果)",
        r"# \1\n\n",
        text,
    )
    # 一级章节
    for section in _L1_SECTIONS:
        text = text.replace(section, f"\n\n## {section}\n\n")
    # 结尾段（审计建议与整改情况）
    text = text.replace(
        "对审计发现的问题，审计署已依法出具了审计报告，提出了审计建议：",
        "\n\n## 审计建议与整改\n\n对审计发现的问题，审计署已依法出具了审计报告，提出了审计建议：",
    )
    # 二级小节：（X）小节标题。 —— 标题内不含标点/数字，避免误伤正文内引用
    text = re.sub(
        r"（([一二三四五六七八九十])）([^。，；、：\d%]{2,30})。",
        r"\n\n### （\1）\2。\n\n",
        text,
    )
    return text.strip() + "\n"


def seed(session: Session, storage: FileStorage) -> tuple[User, int]:
    user = session.scalar(select(User).where(User.username == "demo"))
    if user is None:
        user = User(username="demo", password_hash=hash_password("DemoPass-2026!"), role=Role.admin)
        session.add(user)
        session.flush()
    project = session.scalar(select(Project).where(Project.name == PROJECT_NAME))
    if project is None:
        project = create_project(session, PROJECT_NAME, user)
    document = session.scalar(
        select(Document).where(Document.project_id == project.id, Document.title == DOCUMENT_TITLE)
    )
    if document is None:
        document = create_document(session, UUID(project.id), DOCUMENT_TITLE, "审计", "政府公告", user)
    imported = 0
    existing_count = len(
        list(
            session.scalars(
                select(DocumentVersion).where(DocumentVersion.document_id == document.id)
            )
        )
    )
    # 按目标版本数幂等：已有版本数达标则跳过，否则按顺序补齐剩余年度
    for filename in SOURCES[existing_count:]:
        raw = (VAULT / filename).read_text(encoding="utf-8")
        create_version(session, storage, UUID(document.id), normalize(raw).encode("utf-8"), user, filename)
        imported += 1
    return user, imported


def main() -> int:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user, imported = seed(session, FileStorage(settings))
            session.commit()
        print(f"政府公告版本导入完成：新建 {imported} 个版本（目标 {len(SOURCES)} 个），用户 {user.username}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
