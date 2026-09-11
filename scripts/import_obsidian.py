from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python scripts/<name>.py` 直接运行（补齐项目根到模块搜索路径）
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentVersion
from app.documents.service import create_version
from app.documents.storage import FileStorage
from app.identity.models import User
from app.knowledge.ingestion import ingest_version
from app.knowledge.models import KnowledgeDocument, KnowledgeSpace, KnowledgeState

_ALLOWED_SUFFIX = ".md"
_PUBLIC_KEYS = ("public", "is_public", "visibility")


@dataclass(frozen=True)
class ImportItem:
    source: str
    title: str
    content_sha256: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "ready"
    reason: str | None = None


@dataclass(frozen=True)
class ImportPlan:
    vault: str
    space_id: str
    allowed_directories: tuple[str, ...]
    public_only: bool
    items: tuple[ImportItem, ...]

    @property
    def ready(self) -> tuple[ImportItem, ...]:
        return tuple(item for item in self.items if item.status == "ready")

    def summary(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            result[item.status] = result.get(item.status, 0) + 1
        return result


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip("\"'")
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none"}:
        return None
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the small scalar frontmatter subset needed for import policy."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    metadata: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_scalar(value)
    body_start = end + len("\n---")
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return metadata, text[body_start:]


def _is_public(metadata: dict[str, Any]) -> bool:
    for key in _PUBLIC_KEYS:
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {
            "public",
            "true",
            "yes",
        }:
            return True
    return False


def _safe_allowed_roots(
    vault: Path, allowed_directories: Iterable[str]
) -> tuple[Path, ...]:
    vault = vault.resolve(strict=True)
    roots: list[Path] = []
    for raw in allowed_directories:
        relative = Path(raw)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ValueError(f"Allowed directory must be inside vault: {raw}")
        root = (vault / relative).resolve(strict=True)
        try:
            root.relative_to(vault)
        except ValueError as exc:
            raise ValueError(f"Allowed directory escapes vault: {raw}") from exc
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Allowed directory is not a real directory: {raw}")
        roots.append(root)
    if not roots:
        raise ValueError("At least one allowed directory is required")
    return tuple(roots)


def _within_allowed(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _existing_hashes(session: Session | None, space_id: UUID) -> set[str]:
    if session is None:
        return set()
    rows = session.execute(
        select(DocumentVersion.content_sha256)
        .join(KnowledgeDocument, KnowledgeDocument.version_id == DocumentVersion.id)
        .where(KnowledgeDocument.space_id == str(space_id))
    )
    return {row[0] for row in rows}


def scan_vault(
    vault: str | Path,
    allowed_directories: Iterable[str],
    *,
    space_id: UUID | str,
    public_only: bool = False,
    session: Session | None = None,
) -> ImportPlan:
    vault_path = Path(vault).resolve(strict=True)
    space_uuid = UUID(str(space_id))
    roots = _safe_allowed_roots(vault_path, allowed_directories)
    hashes = _existing_hashes(session, space_uuid)
    seen: set[str] = set()
    items: list[ImportItem] = []
    candidates = sorted({path for root in roots for path in root.rglob("*")})
    for path in candidates:
        relative = path.relative_to(vault_path).as_posix()
        if path.is_symlink():
            items.append(
                ImportItem(
                    relative, path.stem, None, status="rejected", reason="symlink"
                )
            )
            continue
        resolved = path.resolve()
        if not _within_allowed(resolved, roots):
            items.append(
                ImportItem(
                    relative, path.stem, None, status="rejected", reason="path_escape"
                )
            )
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() != _ALLOWED_SUFFIX:
            items.append(
                ImportItem(
                    relative, path.stem, None, status="skipped", reason="markdown_only"
                )
            )
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeDecodeError) as exc:
            items.append(
                ImportItem(
                    relative,
                    path.stem,
                    None,
                    status="rejected",
                    reason=type(exc).__name__,
                )
            )
            continue
        metadata, content = parse_frontmatter(text)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if public_only and not _is_public(metadata):
            items.append(
                ImportItem(
                    relative,
                    path.stem,
                    digest,
                    metadata,
                    status="skipped",
                    reason="not_public",
                )
            )
        elif digest in hashes or digest in seen:
            items.append(
                ImportItem(
                    relative,
                    path.stem,
                    digest,
                    metadata,
                    status="duplicate",
                    reason="same_content",
                )
            )
        else:
            seen.add(digest)
            items.append(ImportItem(relative, path.stem, digest, metadata))
    return ImportPlan(
        vault_path.as_posix(),
        str(space_uuid),
        tuple(root.relative_to(vault_path).as_posix() for root in roots),
        public_only,
        tuple(items),
    )


def apply_import(
    plan: ImportPlan,
    session: Session,
    storage: FileStorage,
    actor: User,
    *,
    project_id: UUID,
) -> list[DocumentVersion]:
    if not plan.ready:
        return []
    space = session.get(KnowledgeSpace, plan.space_id)
    if space is None:
        raise ValueError("Knowledge space not found")
    vault = Path(plan.vault)
    created: list[DocumentVersion] = []
    for item in plan.ready:
        path = vault / item.source
        content = parse_frontmatter(path.read_text(encoding="utf-8"))[1].encode("utf-8")
        document = Document(
            project_id=str(project_id),
            owner_id=actor.id,
            title=item.title,
            domain=str(item.metadata.get("domain", "imported")),
            document_type=str(item.metadata.get("document_type", "report")),
        )
        session.add(document)
        session.flush()
        version = create_version(
            session, storage, UUID(document.id), content, actor, item.source
        )
        knowledge = KnowledgeDocument(
            version_id=version.id,
            space_id=space.id,
            state=KnowledgeState.indexed,
            metadata_=dict(item.metadata) | {"source": item.source, "imported": True},
        )
        session.add(knowledge)
        session.flush()
        ingest_version(session, storage, UUID(version.id), UUID(space.id))
        created.append(version)
    return created


def _print_plan(plan: ImportPlan) -> None:
    print(
        json.dumps(
            {"dry_run": True, "summary": plan.summary(), "space_id": plan.space_id},
            ensure_ascii=False,
        )
    )
    for item in plan.items:
        print(json.dumps(asdict(item), ensure_ascii=False))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely import selected Markdown directories from an Obsidian vault."
    )
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--space-id", required=True, type=UUID)
    parser.add_argument(
        "--allow-dir", action="append", dest="allowed_directories", required=True
    )
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist imported versions; default is dry-run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = scan_vault(
            args.vault,
            args.allowed_directories,
            space_id=args.space_id,
            public_only=args.public_only,
        )
        if not args.apply:
            _print_plan(plan)
            return 0
        raise RuntimeError(
            "--apply requires an application integration with an authenticated actor and project_id"
        )
    except (OSError, ValueError) as exc:
        print(f"Import refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
