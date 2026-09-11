from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterable

from app.agent.messages import AssistantMessage, ToolCall
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderError,
)

# 离线演示：识别检索意图词，触发 search_knowledge 工具调用闭环
_RETRIEVAL_INTENT = re.compile(r"检索|搜索|知识库|查找|查一下|查查|引用|依据|根据|参考资料|先例|案例")
# 起草意图：命中后调用 draft_document，走「生成草稿 → 用户确认保存」链路
_DRAFT_INTENT = re.compile(r"起草|拟一份|拟写|写一份|写一篇|撰写|草拟|帮我写")
# 从「起草一份《XXX》」类句式提取标题
_DRAFT_TITLE = re.compile(r"[《\"]([^》\"]{2,120})[》\"]")


def _demo_draft_body(user_text: str) -> str:
    requirement = user_text.strip()[:200]
    return (
        "# 草稿标题\n\n"
        "## 起草要求\n"
        f"{requirement}\n\n"
        "## 一、基本情况\n"
        "（此处填写审计事项、范围与依据。）\n\n"
        "## 二、发现的问题\n"
        "1. 待补充：问题事实；\n"
        "2. 待补充：证据来源与对应条款。\n\n"
        "## 三、整改建议\n"
        "（建议应逐条对应上述问题，明确责任主体与完成时限。）\n\n"
        "说明：这是离线演示生成的骨架草稿，请在正文中补充真实事实与证据后再提交。"
    )
# 从消息中提取检索宾语（如“根据知识库检索一下责任分工的内容”→“责任分工”），
# 避免整句作为 FTS 查询（单字 AND 语义下整句必然 0 命中）
_RETRIEVAL_QUERY = re.compile(r"(?:检索|搜索|查找|查一下|查查)(?:一下)?(.+?)(?:的内容|相关内容|相关资料|的资料|的信息|信息)?[。？?!！ ]*$")
# 检索词降级：剥离泛化后缀后取核心二字词（中文 FTS 单字 AND 下，
# “差旅补助标准”这类长词组很难在单个块中全部命中，降级为“差旅”后可命中）
_GENERIC_SUFFIX = re.compile(r"(标准|要求|规定|流程|制度|内容|情况|说明|政策|条款|办法|清单|材料|记录|报告)+$")


def _core_term(query: str) -> str:
    trimmed = _GENERIC_SUFFIX.sub("", query.strip())
    if len(trimmed) >= 2:
        query = trimmed
    return query[:2] if len(query) > 2 else query


class FakeProvider(ModelProvider):
    """Deterministic provider that records every completion request.

    无脚本（``responses is None``）时进入离线演示模式，此时 ``offline=True``：
    语义分析类任务会走本地启发式而不是假装调用了模型。带脚本时它是真实模型的测试替身。
    """

    def __init__(
        self, responses: Iterable[AssistantMessage | CompletionResult | Exception] | None = None
    ) -> None:
        self.responses = deque(responses) if responses is not None else deque()
        self._demo_mode = responses is None
        self.offline = self._demo_mode
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self._demo_mode:
            return self._demo_complete(request)
        if not self.responses:
            raise ProviderError("provider_unavailable", retryable=False)
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        if isinstance(response, CompletionResult):
            return response
        try:
            return CompletionResult(
                content=response.content,
                tool_calls=[call.to_provider() for call in response.tool_calls],
            )
        except ValueError as exc:
            raise ProviderError("provider_invalid_response") from exc

    def _demo_complete(self, request: CompletionRequest) -> CompletionResult:
        last = request.messages[-1] if request.messages else None
        if last is not None and last.role == "tool":
            return self._demo_after_tool(last.name or "", last.content or "", last.tool_call_id or "", request)
        user_text = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "",
        )
        has_draft_tool = any(tool.get("name") == "draft_document" for tool in request.tools)
        if user_text and has_draft_tool and _DRAFT_INTENT.search(user_text):
            title = _DRAFT_TITLE.search(user_text)
            call = ToolCall(
                id="demo-draft-1",
                name="draft_document",
                arguments=json.dumps(
                    {
                        "title": (title.group(1).strip() if title else "新建审计文书草稿")[:120],
                        "content": _demo_draft_body(user_text),
                        "notes": "离线演示草稿：由本地 FakeProvider 生成，仅供演示「起草 → 确认保存」链路，内容未使用模型生成。",
                    },
                    ensure_ascii=False,
                ),
            )
            return CompletionResult(content=None, tool_calls=[call.to_provider()])
        has_search_tool = any(tool.get("name") == "search_knowledge" for tool in request.tools)
        if user_text and has_search_tool and _RETRIEVAL_INTENT.search(user_text):
            match = _RETRIEVAL_QUERY.search(user_text.strip())
            query = (match.group(1).strip() if match and match.group(1).strip() else user_text.strip())[:200]
            call = ToolCall(
                id="demo-search-1",
                name="search_knowledge",
                arguments=json.dumps({"query": query, "mode": "keyword", "limit": 5}, ensure_ascii=False),
            )
            return CompletionResult(content=None, tool_calls=[call.to_provider()])
        return CompletionResult(content="离线演示回复：已收到请求。当前使用本地 FakeProvider，未调用外部模型。")

    def _demo_after_tool(self, name: str, content: str, tool_call_id: str, request: CompletionRequest) -> CompletionResult:
        if name == "draft_document":
            try:
                payload = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                payload = None
            if isinstance(payload, dict) and payload.get("title") and payload.get("content"):
                return CompletionResult(
                    content=(
                        f"已为你起草《{payload['title']}》草稿（{len(str(payload['content']))} 字），"
                        "内容如下，可点击下方「保存为草稿」写入编辑器，再经「保存为新版本」落库：\n\n"
                        f"{payload['content']}"
                    )
                )
            return CompletionResult(content="草稿生成失败：工具未返回有效内容。（离线演示回复）")
        if name == "search_knowledge":
            try:
                payload = json.loads(content)
                hits = payload.get("hits") if isinstance(payload, dict) else None
            except (json.JSONDecodeError, TypeError):
                hits = None
            if isinstance(hits, list) and hits:
                return self._demo_summarize_hits(hits)
            # 首轮检索 0 命中：降级为核心二字词重试一次（模拟真实 Agent 的检索策略）
            if tool_call_id == "demo-search-1":
                user_text = next(
                    (message.content for message in reversed(request.messages) if message.role == "user"),
                    "",
                )
                match = _RETRIEVAL_QUERY.search(user_text.strip())
                query = (match.group(1).strip() if match and match.group(1).strip() else user_text.strip())[:200]
                core = _core_term(query)
                if core and core != query:
                    call = ToolCall(
                        id="demo-search-2",
                        name="search_knowledge",
                        arguments=json.dumps({"query": core, "mode": "keyword", "limit": 5}, ensure_ascii=False),
                    )
                    return CompletionResult(content=None, tool_calls=[call.to_provider()])
            return CompletionResult(content="知识库中未检索到相关内容。可以先将文档版本晋升入共享知识库，或收入个人知识库后再试。（离线演示回复）")
        return CompletionResult(content="离线演示回复：工具调用已完成。当前使用本地 FakeProvider，未调用外部模型。")

    def _demo_summarize_hits(self, hits: list) -> CompletionResult:
        lines = [f"已从知识库检索到 {len(hits)} 条相关来源："]
        for index, hit in enumerate(hits, start=1):
            if not isinstance(hit, dict):
                continue
            heading = " / ".join(hit.get("heading_path") or [])
            quote = (hit.get("quote") or "").strip()
            if len(quote) > 80:
                quote = quote[:80] + "…"
            location = f"（{heading}）" if heading else ""
            lines.append(f"{index}. 《{hit.get('title', '未命名文档')}》{location}：{quote}")
        lines.append("以上内容来自你授权范围内的已索引知识来源。（离线演示：由本地 FakeProvider 基于检索结果生成）")
        return CompletionResult(content="\n".join(lines))


__all__ = ["FakeProvider"]
