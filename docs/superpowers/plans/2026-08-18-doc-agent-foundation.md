# Doc Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first runnable vertical slice of Doc Agent: local authentication, immutable document versions, bounded Agent chat with fake/live provider adapters, personal/shared knowledge ingestion and retrieval with citations, document comparison, review workflow, and approved RAG promotion.

**Architecture:** A React/TypeScript frontend calls a FastAPI modular monolith. SQLAlchemy and Alembic persist identity, documents, reviews, jobs, and knowledge metadata in SQLite while keeping PostgreSQL-compatible boundaries; a typed provider and job-runner interface isolate external models and long work.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic 2, pydantic-settings, SQLAlchemy 2, Alembic, SQLite FTS5, PyJWT, pwdlib/Argon2, httpx, pytest, React, TypeScript, Vite, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-18-doc-agent-design.md`

## Global Constraints

- Project root is `D:\workspace1\doc-agent`.
- Python environments and dependencies use uv; never install into global Python.
- Research using public model APIs may process public material only.
- AI analyses, reviews, approvals, and indexing always target immutable document versions.
- Client chat accepts only user-authored text; server creates system, assistant, and tool messages.
- Retrieval permissions are applied before ranking.
- Personal and unapproved documents cannot appear in another user's results.
- Important AI findings include source locations and citations or explicitly report no supporting source.
- High-risk logical findings remain candidates for human review.
- Mutating Agent tools require server-side authorization and explicit UI confirmation.
- Normal automated tests require no network access.
- Do not implement real-time editing, external document-platform integration, multi-agent orchestration, or graph visualization in this plan.

## File Map

```text
pyproject.toml                         Python dependencies and test configuration
uv.lock                                Reproducible Python lock
.env.example                           Non-secret configuration contract
alembic.ini / alembic/                 Database migrations
app/main.py                            FastAPI composition and error middleware
app/core/config.py                     Validated settings
app/core/errors.py                     Stable application error taxonomy
app/core/security.py                   Passwords and JWT
app/db/base.py                         SQLAlchemy declarative base
app/db/session.py                      Engine and transaction/session dependency
app/identity/                          User model, schemas, repository, service, API
app/projects/                          Project and membership authorization
app/documents/                         Documents, immutable versions, files, API
app/reviews/                           Submission, comments, decisions, workflow API
app/jobs/                              Persistent local job model and runner
app/knowledge/                         Spaces, chunks, ingestion, FTS retrieval, citations
app/providers/                         Fake and OpenAI-compatible model providers
app/agent/                             Tool registry, bounded loop, chat API
app/quality/                           Structured findings and comparison tool
web/                                   React Agent workspace
scripts/bootstrap_admin.py             First administrator creation
scripts/import_obsidian.py             Safe public-material import command
run_worker.py                          Local persistent job worker
run_dev.py                             Development launcher

tests/unit/                            Pure unit tests
tests/integration/                     Temporary-database API tests
tests/fixtures/                        Public, synthetic documents and model replies
web/src/**/*.test.tsx                  Frontend unit/component tests
web/e2e/                               Playwright critical workflow
```

---

### Task 1: Bootable Backend and Error Contract

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/core/config.py`
- Create: `app/core/errors.py`
- Create: `tests/conftest.py`
- Create: `tests/integration/test_health.py`
- Create: `tests/integration/test_errors.py`

**Interfaces:**
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`
- Produces: `Settings(database_url: str, jwt_secret: SecretStr, model_provider: str, storage_dir: Path)`
- Produces: `AppError(code: str, message: str, status_code: int, retryable: bool = False)`
- Produces API error shape: `{error: {code, message, request_id, retryable}}`

- [ ] **Step 1: Initialize the Python project and lock dependencies**

Run:

```bash
uv init --bare --python 3.12
uv add fastapi "uvicorn[standard]" pydantic-settings sqlalchemy alembic pyjwt "pwdlib[argon2]" python-multipart httpx
uv add --dev pytest pytest-asyncio pytest-cov ruff
```

Expected: `pyproject.toml` and `uv.lock` are created with no global installation.

- [ ] **Step 2: Write failing health and error-envelope tests**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ready():
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_missing_route_uses_safe_error_envelope():
    response = TestClient(create_app()).get("/api/not-present")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "not_found"
    assert body["request_id"]
    assert body["retryable"] is False
```

- [ ] **Step 3: Run tests and verify collection fails**

Run: `uv run pytest tests/integration/test_health.py tests/integration/test_errors.py -v`

Expected: FAIL because `app.main` does not exist.

- [ ] **Step 4: Implement settings, application factory, request IDs, and handlers**

Implement `Settings` with `.env` support, a development-only JWT default, `AppError`, handlers for `AppError`, validation errors, HTTP errors, and unexpected exceptions, plus `/api/health`.

Unexpected errors must log the request ID and return `internal_error` without a stack trace.

- [ ] **Step 5: Verify tests and static checks**

Run:

```bash
uv run pytest tests/integration/test_health.py tests/integration/test_errors.py -v
uv run ruff check app tests
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .env.example app tests
 git commit -m "feat: bootstrap FastAPI service"
```

### Task 2: Database, Migrations, and Local Authentication

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_identity.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/identity/models.py`
- Create: `app/identity/schemas.py`
- Create: `app/identity/repository.py`
- Create: `app/identity/service.py`
- Create: `app/identity/router.py`
- Create: `app/core/security.py`
- Create: `scripts/bootstrap_admin.py`
- Create: `tests/integration/test_auth.py`

**Interfaces:**
- Consumes: `Settings`, `AppError`, `create_app`
- Produces: `User(id: UUID, username: str, password_hash: str, role: Role, is_active: bool)`
- Produces: `Role = user | reviewer | admin`
- Produces: `get_current_user() -> User`
- Produces endpoints: `POST /api/auth/login`, `GET /api/auth/me`

- [ ] **Step 1: Write failing authentication tests**

Test that a seeded user can log in, a bad password returns `authentication_error`, `/api/auth/me` requires a token, and an inactive user cannot log in.

```python
def test_login_and_read_current_user(client, user_factory):
    user_factory(username="writer", password="correct", role="user")
    login = client.post("/api/auth/login", data={"username": "writer", "password": "correct"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["username"] == "writer"
    assert me.json()["role"] == "user"
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/integration/test_auth.py -v`

Expected: FAIL because identity endpoints do not exist.

- [ ] **Step 3: Implement SQLAlchemy session and identity schema**

Use UUID strings, UTC timestamps, a unique normalized username, Argon2 password hashing, HS256 JWT with `sub`, `role`, `iat`, and `exp`, and a 30-minute default expiry.

- [ ] **Step 4: Add migration and bootstrap command**

`scripts/bootstrap_admin.py` accepts `--username` and reads the password using `getpass`; it must refuse duplicate usernames and never print the password.

- [ ] **Step 5: Run migration and tests**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_auth.py -v
```

Expected: migration and tests PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic app/db app/identity app/core/security.py scripts tests/integration/test_auth.py
 git commit -m "feat: add local account authentication"
```

### Task 3: Projects and Resource-Scoped Authorization

**Files:**
- Create: `alembic/versions/0002_projects.py`
- Create: `app/projects/models.py`
- Create: `app/projects/schemas.py`
- Create: `app/projects/service.py`
- Create: `app/projects/router.py`
- Create: `app/projects/permissions.py`
- Create: `tests/integration/test_project_permissions.py`

**Interfaces:**
- Consumes: authenticated `User`
- Produces: `Project`, `ProjectMember(project_id, user_id, membership_role)`
- Produces: `require_project_permission(project_id: UUID, action: ProjectAction, user: User, session: Session) -> Project`
- Produces endpoints: create/list project, add/list members

- [ ] **Step 1: Write failing permission tests**

Cover owner creation, member access, non-member denial, reviewer membership, and the rule that global `reviewer` does not grant access to unrelated projects.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/integration/test_project_permissions.py -v`

Expected: FAIL with missing routes/models.

- [ ] **Step 3: Implement project models and explicit action matrix**

Actions are `view`, `edit`, `comment`, `submit`, `review`, and `manage_members`. Store membership role as `contributor`, `reviewer`, or `owner`.

- [ ] **Step 4: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_project_permissions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic app/projects tests/integration/test_project_permissions.py
 git commit -m "feat: add project-scoped permissions"
```

### Task 4: Documents, Immutable Versions, and Safe File Storage

**Files:**
- Create: `alembic/versions/0003_documents.py`
- Create: `app/documents/models.py`
- Create: `app/documents/schemas.py`
- Create: `app/documents/storage.py`
- Create: `app/documents/service.py`
- Create: `app/documents/router.py`
- Create: `tests/unit/test_file_storage.py`
- Create: `tests/integration/test_documents.py`

**Interfaces:**
- Produces: `Document(id, project_id, owner_id, title, domain, document_type, status)`
- Produces: `DocumentVersion(id, document_id, number, content_sha256, storage_key, created_by, created_at)`
- Produces: `create_version(document_id: UUID, content: bytes, actor: User) -> DocumentVersion`
- Produces endpoints for create, upload, version list, and immutable version read

- [ ] **Step 1: Write failing storage and version tests**

Assert generated storage keys never include a user filename, `../` filenames cannot escape storage, duplicate content has stable hashes, version numbers increase transactionally, and stored versions cannot be updated.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_file_storage.py tests/integration/test_documents.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement generated-ID storage and immutable version service**

Accept UTF-8 `.md` and `.txt` initially, limit upload size using settings, normalize line endings, store originals under generated UUID directories, and save SHA-256.

- [ ] **Step 4: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/unit/test_file_storage.py tests/integration/test_documents.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic app/documents tests
 git commit -m "feat: add immutable document versions"
```

### Task 5: Provider Interface and Bounded Agent Loop

**Files:**
- Create: `app/providers/base.py`
- Create: `app/providers/fake.py`
- Create: `app/providers/openai_compatible.py`
- Create: `app/agent/messages.py`
- Create: `app/agent/tools.py`
- Create: `app/agent/loop.py`
- Create: `app/agent/router.py`
- Create: `tests/fixtures/provider/tool_call.json`
- Create: `tests/unit/test_agent_loop.py`
- Create: `tests/integration/test_chat.py`

**Interfaces:**
- Produces: `ModelProvider.complete(request: CompletionRequest) -> CompletionResult`
- Produces: `ToolDefinition(name, description, input_model, handler, mutating, permission)`
- Produces: `AgentRunner.run(user: User, text: str, context: AgentContext) -> AgentResult`
- Produces endpoint: `POST /api/chat` accepting `{text, project_id?, document_version_id?, knowledge_space_ids?}`

- [ ] **Step 1: Write failing loop tests**

Cover final text response, one tool round, multiple tool calls, malformed JSON arguments, unknown tools, denied tools, provider timeout, max rounds, and client attempts to inject system/tool roles.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_agent_loop.py tests/integration/test_chat.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement typed provider and fake provider**

`FakeProvider` returns queued fixture responses. `OpenAICompatibleProvider` owns endpoint, API key, model, timeout, retry count, token usage, and request ID. It retries only retryable transport/provider failures.

- [ ] **Step 4: Implement validated registry and bounded loop**

Parse every tool argument through its Pydantic input model. Initialize trace arguments before parsing. Enforce round, message, duration, and token/cost budgets. Return safe tool errors to the model and structured traces to the client.

- [ ] **Step 5: Verify offline tests**

Run: `uv run pytest tests/unit/test_agent_loop.py tests/integration/test_chat.py -v`

Expected: PASS without API keys or network.

- [ ] **Step 6: Commit**

```bash
git add app/providers app/agent tests
 git commit -m "feat: add bounded Agent runtime"
```

### Task 6: Persistent Jobs and Recoverable Worker

**Files:**
- Create: `alembic/versions/0004_jobs.py`
- Create: `app/jobs/models.py`
- Create: `app/jobs/schemas.py`
- Create: `app/jobs/service.py`
- Create: `app/jobs/runner.py`
- Create: `app/jobs/router.py`
- Create: `run_worker.py`
- Create: `tests/integration/test_jobs.py`

**Interfaces:**
- Produces: `Job(status=queued|running|succeeded|failed|cancelled|retrying)`
- Produces: `enqueue(job_type: str, payload: BaseModel, owner_id: UUID, idempotency_key: str) -> Job`
- Produces: `JobHandler.run(payload: dict) -> dict`
- Produces endpoints: get/list/retry/cancel job

- [ ] **Step 1: Write failing lifecycle tests**

Cover enqueue, duplicate idempotency key, success, retryable failure, non-retryable failure, cancellation before start, ownership isolation, heartbeat, and stale-running recovery.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/integration/test_jobs.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement transactional claim and recovery**

The worker claims one queued job transactionally, stores heartbeat and attempts, and marks jobs stale after a configured timeout. Handler errors store safe summaries and request IDs, not stack traces in API fields.

- [ ] **Step 4: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_jobs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic app/jobs run_worker.py tests/integration/test_jobs.py
 git commit -m "feat: add recoverable background jobs"
```

### Task 7: Knowledge Spaces, Ingestion, FTS, and Citations

**Files:**
- Create: `alembic/versions/0005_knowledge.py`
- Create: `app/knowledge/models.py`
- Create: `app/knowledge/schemas.py`
- Create: `app/knowledge/chunking.py`
- Create: `app/knowledge/ingestion.py`
- Create: `app/knowledge/search.py`
- Create: `app/knowledge/citations.py`
- Create: `app/knowledge/router.py`
- Create: `tests/fixtures/documents/public_audit_excerpt.md`
- Create: `tests/unit/test_chunking.py`
- Create: `tests/integration/test_knowledge_isolation.py`
- Create: `tests/integration/test_search_citations.py`

**Interfaces:**
- Produces: `KnowledgeSpace(kind=personal|project|shared|standard, owner_id?, project_id?)`
- Produces: `KnowledgeDocument(version_id, space_id, state, authority_level, metadata)`
- Produces: `KnowledgeChunk(id, version_id, heading_path, start_offset, end_offset, text)`
- Produces: `search(query: SearchQuery, actor: User) -> list[SearchHit]`
- Produces: `Citation(document_id, version_id, chunk_id, title, heading_path, quote, offsets)`

- [ ] **Step 1: Write failing chunk and isolation tests**

Use a synthetic Chinese Markdown fixture. Assert stable IDs, heading paths, non-overlapping offsets, chunk size limits, personal isolation, project membership filtering, unapproved exclusion, and exact citation quotes.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_chunking.py tests/integration/test_knowledge_isolation.py tests/integration/test_search_citations.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement metadata-first ingestion and SQLite FTS5**

Create chunks from immutable versions, then build a temporary FTS generation and activate it only after all rows succeed. Re-ingesting the same version and space is idempotent. Search first computes authorized space/version IDs, then passes those IDs into the FTS query.

- [ ] **Step 4: Implement citation assembly**

Verify offsets against immutable source text before returning a citation. On mismatch, fail the indexing job rather than emit a false citation.

- [ ] **Step 5: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/unit/test_chunking.py tests/integration/test_knowledge_isolation.py tests/integration/test_search_citations.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic app/knowledge tests
 git commit -m "feat: add permission-aware knowledge retrieval"
```

### Task 8: Dense Retrieval and Hybrid Ranking

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/knowledge/search.py`
- Create: `app/knowledge/embeddings.py`
- Create: `app/knowledge/ranking.py`
- Create: `tests/unit/test_hybrid_ranking.py`
- Create: `tests/integration/test_dense_retrieval.py`

**Interfaces:**
- Produces: `EmbeddingProvider.embed_documents(texts: list[str]) -> ndarray`
- Produces: `EmbeddingProvider.embed_query(text: str) -> ndarray`
- Produces: `reciprocal_rank_fusion(result_lists: list[list[RankedId]], k: int = 60) -> list[RankedId]`
- Extends: `search()` with `keyword|dense|hybrid` modes

- [ ] **Step 1: Add and lock local embedding dependencies**

Run: `uv add fastembed numpy`

Expected: lock updates successfully.

- [ ] **Step 2: Write failing deterministic ranking tests**

Use a fake 3-dimensional embedding provider so tests never download a model. Assert chunk IDs, not `(source, heading)`, are deduplication keys and permission filters apply before vector scoring.

- [ ] **Step 3: Verify failure**

Run: `uv run pytest tests/unit/test_hybrid_ranking.py tests/integration/test_dense_retrieval.py -v`

Expected: FAIL.

- [ ] **Step 4: Implement embeddings and generation activation**

The production provider uses `TextEmbedding(model_name="BAAI/bge-small-zh-v1.5")`, `passage_embed()` for documents, and `query_embed()` for queries. Store float32 vectors by index generation and atomically activate complete generations.

- [ ] **Step 5: Verify tests**

Run: `uv run pytest tests/unit/test_hybrid_ranking.py tests/integration/test_dense_retrieval.py -v`

Expected: PASS with fake embeddings.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock app/knowledge tests
 git commit -m "feat: add hybrid knowledge retrieval"
```

### Task 9: Structured Quality Findings and Core Tools

**Files:**
- Create: `app/quality/schemas.py`
- Create: `app/quality/prompts.py`
- Create: `app/quality/check.py`
- Create: `app/quality/rewrite.py`
- Create: `app/quality/compare.py`
- Create: `app/quality/judge.py`
- Create: `app/quality/review.py`
- Create: `app/quality/tools.py`
- Create: `tests/fixtures/provider/quality_responses.json`
- Create: `tests/unit/test_quality_normalization.py`
- Create: `tests/integration/test_quality_tools.py`

**Interfaces:**
- Produces: `Finding(id, category, severity, source_range, evidence, explanation, suggested_action, citation_ids, confidence, mandatory, human_review_required)`
- Produces: `ComparisonResult(changes, summary, citations)`
- Produces Agent tools: `check_document`, `rewrite_suggestion`, `compare_documents`, `review_comments`, `judge_document`

- [ ] **Step 1: Copy and adapt validated prompt assets**

Copy prompt content from `D:\Obsidian\agent\prompts\` into feature-owned prompt templates. Preserve source assets unchanged; record prompt version names in model requests.

- [ ] **Step 2: Write failing normalization and tool tests**

Test duplicate findings, invalid offsets, inconsistent summary counts, missing citations, candidate logical findings, truncated model output, and version comparison that binds every change to A/B version IDs.

- [ ] **Step 3: Verify failure**

Run: `uv run pytest tests/unit/test_quality_normalization.py tests/integration/test_quality_tools.py -v`

Expected: FAIL.

- [ ] **Step 4: Implement structured prompt calls and normalization**

Reject findings whose evidence does not match immutable source text. Merge duplicates by category and overlapping source range. Logical mismatch findings always set `human_review_required=True`. Never silently truncate source documents; chunk long analyses and aggregate coverage metadata.

- [ ] **Step 5: Register read-only Agent tools and verify**

Run: `uv run pytest tests/unit/test_quality_normalization.py tests/integration/test_quality_tools.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/quality app/agent tests
 git commit -m "feat: add structured document quality tools"
```

### Task 10: Writing Contracts and Supervisor Simulation

**Files:**
- Create: `alembic/versions/0006_contracts.py`
- Create: `app/quality/contracts.py`
- Create: `app/quality/supervisor.py`
- Create: `app/quality/router.py`
- Create: `tests/integration/test_writing_contract.py`
- Create: `tests/integration/test_supervisor_simulation.py`

**Interfaces:**
- Produces: `WritingContract` with versioned requirements and selected standard/precedent IDs
- Produces: `ContractAssessment(requirement_id, status=satisfied|unsatisfied|unknown, evidence)`
- Produces Agent tool: `simulate_supervisor_review`

- [ ] **Step 1: Write failing contract tests**

Cover contract creation, immutable revisions, reviewer confirmation, access control, expired-standard rejection, requirement assessment, and simulation findings being assigned to the author rather than reviewer.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/integration/test_writing_contract.py tests/integration/test_supervisor_simulation.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement contract revisions and simulation context assembly**

Context includes the active contract, authorized active standards, selected approved precedents, current immutable version, and prior project comments. Every simulated concern maps to a contract requirement or a quality category.

- [ ] **Step 4: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_writing_contract.py tests/integration/test_supervisor_simulation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic app/quality tests
 git commit -m "feat: add writing contracts and pre-review"
```

### Task 11: Review Workflow and Comment Response

**Files:**
- Create: `alembic/versions/0007_reviews.py`
- Create: `app/reviews/models.py`
- Create: `app/reviews/schemas.py`
- Create: `app/reviews/workflow.py`
- Create: `app/reviews/service.py`
- Create: `app/reviews/router.py`
- Create: `tests/unit/test_review_state_machine.py`
- Create: `tests/integration/test_review_workflow.py`

**Interfaces:**
- Produces workflow states: `draft`, `submitted`, `in_review`, `changes_requested`, `resubmitted`, `approved`, `promotion_pending`, `indexed`, `archived`
- Produces: `ReviewComment(version_id, source_range, text, status, created_by)`
- Produces: `CommentResponse(comment_id, response_version_id, assessment, reviewer_confirmed)`

- [ ] **Step 1: Write failing state-machine and API tests**

Cover allowed transitions, forbidden transition rollback, reviewer assignment, immutable anchors, comment resolution in a later version, ambiguous AI assessment remaining open, and concurrent decisions returning `version_conflict`.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_review_state_machine.py tests/integration/test_review_workflow.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement transactional workflow and optimistic version checks**

Every mutation accepts the expected workflow revision. Mismatches return `version_conflict`; no silent last-write-wins behavior is allowed.

- [ ] **Step 4: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/unit/test_review_state_machine.py tests/integration/test_review_workflow.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic app/reviews tests
 git commit -m "feat: add document review workflow"
```

### Task 12: Quality Gate and Approved RAG Promotion

**Files:**
- Create: `alembic/versions/0008_promotions.py`
- Create: `app/knowledge/promotion.py`
- Create: `app/quality/gates.py`
- Modify: `app/knowledge/router.py`
- Modify: `app/agent/tools.py`
- Create: `tests/integration/test_promotion.py`

**Interfaces:**
- Produces: `QualityGateResult(status=passed|failed|needs_human_review, findings, policy_version)`
- Produces: `PromotionRequest(version_id, target_space_id, requested_by, reviewed_by, status)`
- Produces mutating Agent tool: `request_knowledge_promotion`

- [ ] **Step 1: Write failing promotion tests**

Cover public-authority auto-policy, internal reviewer requirement, failed gate rejection, non-reviewer denial, idempotent duplicate requests, index failure preserving the approved version, retrieval after success, and revocation removing future hits.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/integration/test_promotion.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement quality policy and promotion job**

The mutating tool creates a pending request only after explicit confirmation. Approval enqueues ingestion. The target space becomes searchable only after the complete index generation activates.

- [ ] **Step 4: Migrate and verify**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_promotion.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alembic app/knowledge app/quality app/agent tests
 git commit -m "feat: add governed RAG promotion"
```

### Task 13: React Agent Workspace

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/src/main.tsx`
- Create: `web/src/app/App.tsx`
- Create: `web/src/api/client.ts`
- Create: `web/src/features/auth/LoginView.tsx`
- Create: `web/src/features/agent/AgentWorkspace.tsx`
- Create: `web/src/features/agent/ToolTrace.tsx`
- Create: `web/src/features/citations/CitationPanel.tsx`
- Create: `web/src/features/jobs/JobStatus.tsx`
- Create: `web/src/app/ErrorBoundary.tsx`
- Create: `web/src/**/*.test.tsx`

**Interfaces:**
- Consumes: auth, chat, job, document, and citation APIs
- Produces: usable login and Agent workspace with explicit confirmation for mutating tools

- [ ] **Step 1: Initialize frontend and install dependencies**

Run:

```bash
npm create vite@latest web -- --template react-ts
npm --prefix web install
npm --prefix web install lucide-react
npm --prefix web install -D vitest jsdom @testing-library/react @testing-library/user-event
```

Expected: React TypeScript app builds.

- [ ] **Step 2: Write failing component tests**

Test login error display, text-only user submission, disabled duplicate send, safe rendering of tool arguments, citation opening, recoverable job failure, and explicit confirmation before a mutating tool request.

- [ ] **Step 3: Verify failure**

Run: `npm --prefix web test -- --run`

Expected: FAIL because feature components do not exist.

- [ ] **Step 4: Implement the quiet work-focused Agent UI**

Use a stable left navigation, central conversation, and right context/citation panel. Render all external/model text through React text nodes; do not use `dangerouslySetInnerHTML`. Keep document controls compact and reserve cards for repeated citations/jobs.

- [ ] **Step 5: Verify tests and build**

Run:

```bash
npm --prefix web test -- --run
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web
 git commit -m "feat: add Agent workspace frontend"
```

### Task 14: Document, Review, Comparison, and Knowledge Views

**Files:**
- Create: `web/src/features/documents/DocumentWorkspace.tsx`
- Create: `web/src/features/documents/VersionList.tsx`
- Create: `web/src/features/comparison/ComparisonView.tsx`
- Create: `web/src/features/reviews/ReviewPanel.tsx`
- Create: `web/src/features/contracts/WritingContractForm.tsx`
- Create: `web/src/features/knowledge/KnowledgeManager.tsx`
- Create: `web/src/features/knowledge/PromotionDialog.tsx`
- Create: associated `*.test.tsx`

**Interfaces:**
- Consumes: document/version, contract, review, comparison, knowledge, and promotion APIs
- Produces: end-to-end asynchronous collaboration UI without real-time editing

- [ ] **Step 1: Write failing workflow component tests**

Cover immutable version selection, source-range highlighting, comments bound to the selected version, conflict refresh prompt, comparison type selection, standard metadata form, promotion target choice, and reviewer-only approval controls.

- [ ] **Step 2: Verify failure**

Run: `npm --prefix web test -- --run`

Expected: FAIL.

- [ ] **Step 3: Implement views and state transitions**

All review mutations send expected workflow revisions. A conflict prompts refresh and preserves unsent local comment text. Comparison clearly labels both immutable versions and never displays an unbound result.

- [ ] **Step 4: Verify frontend**

Run:

```bash
npm --prefix web test -- --run
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features
 git commit -m "feat: add document review and knowledge views"
```

### Task 15: Obsidian Import and Public Evaluation Fixtures

**Files:**
- Create: `scripts/import_obsidian.py`
- Create: `tests/unit/test_obsidian_import.py`
- Create: `tests/evaluation/test_public_audit_baseline.py`
- Create: `tests/fixtures/evaluation/questions.json`
- Create: `tests/fixtures/evaluation/annotations.json`

**Interfaces:**
- Produces command: `uv run python scripts/import_obsidian.py --vault PATH --space-id UUID --public-only`
- Produces evaluation metrics: Recall@6, citation correctness, duplicate finding rate, and comparison coverage

- [ ] **Step 1: Write failing import safety tests**

Cover allowlisted subdirectories, symlink/path escape rejection, Markdown-only input, duplicate version detection, public-only confirmation, metadata mapping, and dry-run output.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/unit/test_obsidian_import.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement safe dry-run-first import**

The command defaults to dry-run, prints counts and destinations, and requires `--apply` to persist. It does not modify the Obsidian vault.

- [ ] **Step 4: Add public evaluation subset**

Adapt only public report excerpts and existing human annotations. Do not copy secrets or internal documents. Evaluation tests use fake provider results unless `LIVE_MODEL_TESTS=1` is set.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/unit/test_obsidian_import.py tests/evaluation -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts tests
 git commit -m "test: add safe vault import and evaluation baseline"
```

### Task 16: End-to-End Verification and Developer Launchers

**Files:**
- Create: `run_dev.py`
- Create: `web/playwright.config.ts`
- Create: `web/e2e/critical-flow.spec.ts`
- Create: `tests/integration/test_failure_recovery.py`
- Modify: `.env.example`

**Interfaces:**
- Produces local URLs: frontend `http://127.0.0.1:5173`, backend `http://127.0.0.1:8000`
- Produces a critical browser flow from login through approved retrieval

- [ ] **Step 1: Add Playwright and write failing critical-flow test**

Run: `npm --prefix web install -D @playwright/test`

The test logs in, imports a fixture, chats with the fake Agent, retrieves a citation, submits a version, adds a reviewer comment, resubmits, approves, promotes, waits for indexing, and verifies a later search returns the approved citation.

- [ ] **Step 2: Write backend failure-recovery tests**

Cover provider timeout, invalid provider payload, stale job recovery, failed indexing followed by retry, optimistic workflow conflict, and citation-offset corruption.

- [ ] **Step 3: Run tests to verify missing launch integration**

Run:

```bash
uv run pytest tests/integration/test_failure_recovery.py -v
npm --prefix web exec playwright test
```

Expected: critical flow fails until launchers and final API wiring exist.

- [ ] **Step 4: Implement development launchers and final wiring**

`run_dev.py` checks configuration, applies migrations, starts backend and local worker, and prints commands/URLs for the Vite frontend without embedding secrets. It refuses to start a live provider without a configured key.

- [ ] **Step 5: Run complete offline verification**

Run:

```bash
uv run ruff check app scripts tests
uv run pytest -v --cov=app
npm --prefix web test -- --run
npm --prefix web run build
npm --prefix web exec playwright test
```

Expected: all checks PASS without network.

- [ ] **Step 6: Run optional public-material live smoke test**

With an explicitly configured key and only the public fixture selected, run one search plus one check. Verify response, citation, latency, token usage, estimated cost, and sanitized logs. This step is skipped when no key is configured.

- [ ] **Step 7: Commit**

```bash
git add run_dev.py .env.example tests web
 git commit -m "test: verify critical Doc Agent workflow"
```

## Plan Self-Review

- Spec coverage: authentication, scoped permissions, immutable versions, Agent loop, five AI tools, comparison, contracts, supervisor simulation, four knowledge spaces, standards governance, jobs, review workflow, promotion, failure preparation, frontend, and future collaboration boundaries are covered.
- Deferred scope remains excluded: no live editing, external platform integration, graph UI, multi-agent orchestration, or SSO.
- Type consistency: document and version IDs are immutable references across quality, review, citation, promotion, and frontend tasks; knowledge search always receives an actor and returns typed citations.
- Network isolation: fake model and fake embeddings cover normal tests; model downloads and live calls are optional only.
