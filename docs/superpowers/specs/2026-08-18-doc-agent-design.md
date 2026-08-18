# Doc Agent Product Design

> Version: 1.0
> Date: 2026-08-18
> Status: Approved for implementation planning

## 1. Product Goal

Build a locally runnable document-quality Agent whose primary outcome is reducing the amount of rewriting supervisors must perform on formal public-facing documents.

The system helps authors understand requirements before writing, retrieve authoritative precedent while writing, detect quality problems before submission, close review comments after submission, and promote approved documents into reusable organizational knowledge.

The product is an AI quality gate, not an autonomous author or final approver.

## 2. Scope

### 2.1 First usable release

The first release provides:

- Local username/password authentication.
- Three roles: user, reviewer, administrator.
- An Agent-first React workspace.
- Document import, version snapshots, submission, review comments, return, resubmission, approval, and RAG promotion.
- Five core AI capabilities: check, rewrite suggestion, comparison, comment review, and document judgement.
- Supervisor-review simulation before submission.
- Hybrid retrieval with traceable citations.
- Personal, project, shared, and standards knowledge spaces.
- AI quality gates plus reviewer approval before internal documents enter shared RAG.
- Background job status, retries, structured errors, and audit events.

### 2.2 Deferred

The first release does not provide:

- Real-time concurrent rich-text editing.
- Feishu, Runwork, or Tencent Docs integration.
- Multi-agent orchestration.
- Autonomous edits to approved documents.
- Complex entity-graph visualization.
- Enterprise SSO.

The architecture reserves integration points for these capabilities.

## 3. Product Principles

1. Suggestions and findings must identify the affected source location.
2. Important AI claims must include a source citation or state that no supporting source was found.
3. AI may mark high-risk logical issues as candidates, but humans make final determinations.
4. Supervisors define requirements and approve outcomes; they should not be required to rewrite subordinates' documents.
5. Only immutable document versions are analysed, reviewed, approved, or indexed.
6. Retrieval permissions are enforced before ranking results.
7. Personal drafts never become organizational precedent without promotion and approval.
8. Standards outrank historical examples; historical usage is not automatically a rule.
9. Research with public models uses public materials only.

## 4. Core User Flow

```text
Login
  -> Create project or open existing project
  -> Create/import document
  -> Select domain, document type, knowledge spaces, precedents, reviewer
  -> Confirm writing contract
  -> Write or upload a draft
  -> Run retrieval, checks, comparison, or rewrite suggestions
  -> Run supervisor-review simulation
  -> Resolve pre-submission findings
  -> Submit immutable version
  -> Reviewer comments, approves, or returns
  -> Author creates a new version and resolves comments
  -> AI verifies comment response and compares versions
  -> Reviewer approves final version
  -> Quality gate runs
  -> Reviewer approves RAG promotion
  -> Approved version becomes retrievable knowledge
```

## 5. Roles and Permissions

### User

- Manage own documents and personal knowledge.
- Access projects where membership is granted.
- Run permitted Agent tools.
- Submit document versions.
- Respond to review comments.
- Request knowledge promotion.

### Reviewer

- All user capabilities.
- Review assigned versions.
- Create paragraph-level comments.
- Return or approve versions.
- Approve or reject internal knowledge promotion.
- Maintain standards within assigned domains.

### Administrator

- Manage users, roles, domains, document types, and knowledge spaces.
- Assign standard maintainers and project membership.
- Archive knowledge and revoke access.
- Inspect audit and failure records.

Authorization is resource-scoped. A role alone does not grant access to every document or project.

## 6. Writing Contract

Every formal document may have a writing contract containing:

- Domain and document type.
- Subject organization and reporting period.
- Purpose and intended audience.
- Required sections.
- Supervisor-specific requirements.
- Selected precedents and templates.
- Applicable standards.
- Required data sources.
- Prohibited wording or disclosure constraints.
- Reviewer and submission deadline.

The contract is versioned. AI checks explicitly report whether each requirement is satisfied, unsatisfied, or cannot be determined.

## 7. AI Capabilities

### 7.1 Document check

Checks spelling, grammar, punctuation, numbers, units, dates, terminology, structure, formatting rules, repetition, internal contradiction, and candidate evidence-conclusion mismatch.

Deterministic rules handle facts that do not need a model. The LLM handles semantic findings. Results are deduplicated and structured.

### 7.2 Rewrite suggestion

Returns a suggestion, reason, affected source range, expected impact, and supporting precedent. It does not overwrite the document.

### 7.3 Comparison

Comparison remains a core capability with three modes:

- Version comparison: immutable version A versus B.
- Precedent comparison: current version versus approved historical example.
- Standards comparison: current version versus applicable standards and templates.

Output covers additions, deletions, semantic rewrites, structural changes, data changes, tone changes, comment response, and citations.

### 7.4 Comment review

Transforms a supervisor comment into explicit requirements, maps it to source text, and later evaluates whether a new version addresses it. Uncertain closure decisions remain open for reviewer confirmation.

### 7.5 Document judgement

Produces structured findings rather than an opaque score. Each finding includes severity, category, source range, evidence, explanation, suggested action, citation, confidence, and whether modification is mandatory.

### 7.6 Supervisor-review simulation

Runs before submission and predicts likely supervisor concerns based on:

- The writing contract.
- Active standards.
- Selected precedents.
- Previous comments from the same project.
- Low-level quality findings.
- Style and factual consistency.

Simulation findings are author tasks, not supervisor tasks. The supervisor only receives the residual issues after the author submits.

## 8. Knowledge Architecture

### 8.1 Spaces

- `personal`: visible to the owner unless shared.
- `project`: visible to project members.
- `shared`: approved organizational knowledge.
- `standard`: authoritative standards and templates.

### 8.2 Knowledge lifecycle

```text
draft -> pending_review -> approved -> indexed -> archived
                   \-> rejected
```

Public authoritative material may be auto-promoted only when its source is verified, malware/type checks pass, duplicate handling succeeds, and the configured policy allows it. Internal and sensitive documents require reviewer approval.

### 8.3 Standard ownership

Standards are maintained by an assigned reviewer or administrator for a domain. A standard records:

- Domain and document type.
- Department/project applicability.
- Authority level.
- Mandatory or advisory status.
- Effective and expiry dates.
- Source and issuer.
- Maintainer and approver.
- Version and superseded standard.

Retrieval priority is:

```text
law/regulation
> active organization standard
> active department standard
> project requirement
> document writing contract
> approved precedent
> personal reference
```

Conflicts are surfaced for reviewer decision; the Agent does not silently resolve them.

### 8.4 Retrieval pipeline

```text
permission and scope filter
-> metadata filter
-> SQLite FTS5 keyword candidates
-> local dense-vector candidates
-> reciprocal-rank fusion
-> optional reranking
-> citation assembly
```

Every chunk has a stable `chunk_id`, `document_id`, `version_id`, heading path, source offsets, knowledge space, approval state, and authority level.

## 9. Collaboration Model

The first release uses asynchronous version collaboration:

```text
draft -> submitted -> in_review -> changes_requested
      -> resubmitted -> approved -> promotion_pending -> indexed
```

Review comments are anchored to immutable source ranges in a submitted version. Authors answer comments in a new version. The system maps old ranges to new content where possible, but a reviewer confirms ambiguous mappings.

The database reserves `editor_provider` and `collaboration_room_id`. A future real-time editor can use React, Tiptap, Yjs, and Hocuspocus. AI analysis always creates or targets an immutable snapshot even when live editing is later enabled.

## 10. Architecture

### Frontend

React, TypeScript, and Vite provide:

- Agent workspace.
- Document workspace.
- Citation viewer.
- Review and approval center.
- Version comparison.
- Knowledge administration.
- Job and error status.

### Backend

FastAPI is deployed as a modular monolith with feature-oriented modules:

- identity
- projects
- documents
- reviews
- knowledge
- agent
- quality
- jobs
- audit

Each feature owns API schemas, services, repository operations, and tests. Cross-feature calls use typed service interfaces.

### Persistence

- SQLAlchemy 2.x ORM.
- SQLite for local development and first release.
- Alembic migrations from the first schema.
- PostgreSQL-compatible schema and transaction patterns.
- Original files stored outside the database under generated IDs.
- Metadata, versions, workflow state, citations, jobs, and audit events stored in the database.

### Background work

A `JobRunner` interface separates HTTP APIs from long-running operations. The first release uses a local database-backed worker. A later deployment may replace it with Redis plus Celery or another worker without changing API contracts.

Long-running operations include ingestion, embedding, full judgement, large comparison, and knowledge promotion.

### Model providers

A typed provider interface supports OpenAI-compatible services. Configuration selects endpoint and model. Provider calls implement timeout, bounded retries, usage collection, empty-response validation, tool schema validation, and trace IDs.

## 11. Agent Runtime

The Agent is a bounded loop, not a multi-agent system.

Controls include:

- Maximum tool rounds.
- Maximum request history and token budget.
- Strict client message roles.
- Pydantic-validated tool arguments.
- Per-tool authorization.
- Per-request cost and duration budget.
- Idempotency keys for mutating tools.
- Safe tool error messages.
- Immutable version references.

Mutating actions such as submission or promotion require explicit user confirmation in the UI and server-side permission checks. The model cannot grant itself permission.

## 12. Reliability and Error Preparation

### Error taxonomy

- `validation_error`
- `authentication_error`
- `permission_denied`
- `not_found`
- `version_conflict`
- `provider_unavailable`
- `provider_invalid_response`
- `index_failure`
- `job_failure`
- `internal_error`

API errors expose a stable code, safe message, request ID, and retryability. Stack traces and sensitive arguments remain in structured local logs.

### Fault controls

- Provider timeout and bounded exponential retry.
- No retries for validation or permission errors.
- Idempotent ingestion and promotion.
- Transactional workflow transitions.
- Job heartbeat and stale-job recovery.
- Index build in a temporary generation followed by atomic activation.
- Original document retained when indexing fails.
- Frontend error boundary and recoverable job display.
- Database backup and restore command before multi-user deployment.

### Observability

Record:

- Request ID and user ID.
- Document/version IDs.
- Agent rounds and tool calls.
- Model, token usage, latency, retry count, and estimated cost.
- Retrieval candidates and selected citations.
- Workflow transitions.
- Knowledge promotion and revocation.
- Sanitized exceptions.

## 13. Testing Strategy

### Unit tests

Cover state transitions, permissions, writing contracts, chunking, metadata filters, ranking fusion, citations, tool validation, comparison normalization, and error mapping.

### Integration tests

Use a temporary SQLite database and fake model provider to cover authentication, document versioning, review workflow, Agent tool execution, ingestion, retrieval isolation, and promotion.

### Golden evaluations

Use the existing public audit reports and human annotations to measure:

- Low-level finding precision and recall.
- Retrieval Recall@K.
- Citation correctness.
- Duplicate finding rate.
- Comparison coverage.
- Comment-response classification.
- Supervisor residual edit count.

### End-to-end tests

Use Playwright for login, Agent chat, import, submission, comment response, approval, promotion, and subsequent retrieval.

Live-provider smoke tests are opt-in and never required for the normal test suite.

## 14. Success Criteria

The first usable release is accepted when:

- A local user can log in and use Agent chat.
- A user can import a public audit document and create immutable versions.
- Agent tools perform search, check, rewrite suggestion, comparison, comment review, judgement, and supervisor simulation.
- Retrieval results include valid source citations and respect knowledge-space permissions.
- A user can submit a version, a reviewer can comment and return it, and a later version can be approved.
- An approved version can pass a quality gate, receive reviewer promotion approval, enter the selected knowledge space, and be retrieved afterward.
- Personal or unapproved content cannot appear in another user's retrieval.
- Model and indexing failures produce recoverable jobs rather than lost documents.
- Automated tests cover the critical workflow without requiring network access.

## 15. Delivery Stages

### Stage 1: Executable foundation

Authentication, database, document versions, Agent chat shell, fake provider, structured errors, and test infrastructure.

### Stage 2: Knowledge and core AI

Ingestion, FTS/vector retrieval, citations, migrated prompts, five core capabilities, comparison, and evaluation fixtures.

### Stage 3: Review and promotion loop

Writing contracts, supervisor simulation, comments, workflow, quality gates, approval, and RAG promotion.

### Stage 4: Product hardening

Background worker recovery, audit UI, Playwright coverage, backups, performance limits, and live-provider smoke tests.

### Future: Rich collaboration

Tiptap document workspace, Yjs/Hocuspocus real-time synchronization, live presence, persistent comments, and external platform adapters.
