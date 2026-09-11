"""批量导入演示知识库：合成管理制度与历史审计文档，充实共享知识库检索。

幂等：按标题跳过已存在的文档。文档直接进入共享知识库索引，
等价于"历史已批准知识"，无需走晋升流程。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python scripts/<name>.py` 直接运行（补齐项目根到模块搜索路径）
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import KnowledgeSpace, KnowledgeSpaceKind
from app.projects.models import Project
from app.projects.service import create_project

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "DemoPass-2026!"
PROJECT_NAME = "知识库：管理制度与历史审计"

DOCUMENTS: list[tuple[str, str, str, str]] = [
    (
        "采购管理办法（试行）",
        "采购",
        "制度",
        """# 采购管理办法（试行）

## 适用范围

本办法适用于本单位所有货物、工程和服务的采购活动，包括集中采购与分散采购。

## 比价要求

单笔金额 5 万元以下的采购事项，应留存不少于三家供应商的报价记录；5 万元以上的采购原则上应通过公开比价或招标方式确定供应商。所有比价材料由采购部门归档留存不少于五年。

## 审批权限

采购申请由部门负责人初审，财务部门复核预算，分管领导审批。10 万元以上采购须报采购委员会集体决策。

## 验收与付款

货物验收由使用部门与采购部门共同完成，验收合格后方可付款。付款前须核对合同、发票、验收单与比价记录的一致性。
""",
    ),
    (
        "财务报销管理制度",
        "财务",
        "制度",
        """# 财务报销管理制度

## 报销范围

本办法规范差旅费、业务招待费、办公费、培训费等各类费用的报销流程与标准。

## 报销流程

经办人填写报销单并附原始凭证，部门负责人审核业务真实性，财务部门审核票据合规性，分管领导按权限审批。

## 票据要求

报销发票须为合规增值税发票或财政票据，抬头与单位名称一致。电子发票须查验真伪并防重复报销。票据缺失或不符合规定的，财务部门有权退回。

## 付款时限

审批完成的报销单，财务部门应在 10 个工作日内完成付款。急件可走绿色通道，但事后须补齐全部手续。
""",
    ),
    (
        "合同管理规范",
        "法务",
        "制度",
        """# 合同管理规范

## 合同起草

合同起草应使用标准模板，重大合同应由法务部门参与起草或审核。合同编号遵循"年份-类别-流水号"规则。

## 审批签署

合同签署前须经业务、财务、法务三部门会签。超过 50 万元的合同须报单位负责人签署，并加盖单位公章或合同专用章。

## 履约管理

合同履行过程中发生的变更、补充协议须走原审批流程。合同到期前 30 天，经办部门应评估是否续签。

## 归档要求

合同正本一式多份，签署完成后 10 个工作日内归档至档案室，同时登记合同台账。
""",
    ),
    (
        "2025 年度内部审计工作报告",
        "审计",
        "报告",
        """# 2025 年度内部审计工作报告

## 审计概况

2025 年度共完成审计项目 12 个，覆盖采购管理、费用报销、合同履约、资产管理和信息系统五个领域。

## 主要发现

一是部分采购事项缺少完整比价记录，涉及金额约 40 万元；二是少数报销票据不合规，存在电子发票重复报销风险；三是部分合同未及时归档，台账登记不完整。

## 整改情况

上年度审计发现的问题已完成整改 8 项，2 项持续推进。采购比价材料缺失问题已通过建立比价材料清单模板加以规范。

## 工作建议

建议加强采购、报销关键环节的穿行测试频次，推进合同台账电子化管理，并将审计整改纳入部门年度考核。
""",
    ),
    (
        "差旅费管理办法",
        "财务",
        "制度",
        """# 差旅费管理办法

## 交通标准

员工出差乘坐交通工具标准：普通员工火车硬席、轮船三等舱；部门负责人高铁一等座、轮船二等舱。确因工作需要乘飞机的，须事先经分管领导批准。

## 住宿标准

住宿费在限额内凭发票实报实销：一线城市普通员工每晚 500 元，其他城市 400 元；部门负责人相应上浮 200 元。

## 补助规定

伙食补助费每人每天 100 元，市内交通费每人每天 80 元，包干使用。参加会议、培训由举办方统一安排食宿的，不再领取补助。

## 报销时限

差旅结束后 15 个工作日内办理报销，逾期未报销的，财务部门将予以提示并记录。
""",
    ),
    (
        "印章使用管理规定",
        "行政",
        "制度",
        """# 印章使用管理规定

## 印章种类

本单位印章包括公章、合同专用章、财务专用章、发票专用章及法定代表人名章。

## 用印审批

使用公章须填写用印审批单，注明用印事由、文件名称与份数，经部门负责人和办公室审核，分管领导批准。对外签署合同的用印须同时核对会签记录。

## 印章保管

印章由办公室专人保管，财务专用章与法定代表人名章分人保管。印章外带须两人同行并做好登记。

## 禁止行为

严禁在空白纸张、空白介绍信上用印。发现印章遗失应立即报告并公告作废。
""",
    ),
    (
        "信息安全管理制度",
        "信息",
        "制度",
        """# 信息安全管理制度

## 账号权限

信息系统账号实行实名制，人员入职、转岗、离职时应在 3 个工作日内完成账号开通与权限调整。禁止共用账号与转借密码。

## 数据分级

数据按敏感程度分为公开、内部、秘密三级。秘密级数据的存储、传输须加密，外发须审批并留痕。

## 移动存储

涉密计算机严禁连接互联网，移动存储介质须专用专管，接入前须病毒查杀。

## 应急处置

发生信息安全事件时，应立即断网止损、保护现场，并在 2 小时内报告信息安全负责人。
""",
    ),
    (
        "档案管理办法",
        "行政",
        "制度",
        """# 档案管理办法

## 归档范围

本单位在经营管理中形成的具有保存价值的文字、图表、声像等材料均属归档范围，包括合同、财务凭证、审计报告、会议纪要等。

## 归档时限

各部门应在次年 3 月底前完成上年度应归档文件的整理移交。合同签署后 10 个工作日内归档，审计报告出具后 1 个月内归档。

## 保管期限

档案保管期限分为永久、30 年、10 年三种。财务凭证保管 30 年，年度审计报告永久保存。

## 借阅利用

借阅档案须登记并经档案管理员同意，秘密级档案借阅须分管领导批准。档案数字化副本优先提供利用，原件原则上不出库。
""",
    ),
]


def seed_knowledge(session: Session, storage: FileStorage) -> tuple[User, int]:
    user = session.scalar(select(User).where(User.username == DEMO_USERNAME))
    if user is None:
        user = User(username=DEMO_USERNAME, password_hash=hash_password(DEMO_PASSWORD), role=Role.admin)
        session.add(user)
        session.flush()
    project = session.scalar(select(Project).where(Project.name == PROJECT_NAME))
    if project is None:
        project = create_project(session, PROJECT_NAME, user)
    space = session.scalar(select(KnowledgeSpace).where(KnowledgeSpace.kind == KnowledgeSpaceKind.shared))
    if space is None:
        space = KnowledgeSpace(kind=KnowledgeSpaceKind.shared)
        session.add(space)
        session.flush()
    created = 0
    for title, domain, document_type, content in DOCUMENTS:
        document = session.scalar(
            select(Document).where(Document.project_id == project.id, Document.title == title)
        )
        if document is None:
            document = create_document(session, UUID(project.id), title, domain, document_type, user)
            created += 1
        version = session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id, DocumentVersion.number == 1
            )
        )
        if version is None:
            version = create_version(
                session, storage, UUID(document.id), content.encode(), user, f"{title}.md"
            )
        ingest_version(session, storage, UUID(version.id), UUID(space.id))
    return user, created


def main() -> int:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user, created = seed_knowledge(session, FileStorage(settings))
            session.commit()
        total = len(DOCUMENTS)
        print(f"知识库演示数据已就绪：共 {total} 份文档（本次新建 {created} 份），用户 {user.username}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
