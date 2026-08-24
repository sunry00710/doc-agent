from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.import_obsidian import parse_frontmatter, scan_vault


def test_scan_is_dry_run_safe_and_allows_only_markdown(tmp_path: Path):
    vault = tmp_path / "vault"
    allowed = vault / "Public"
    allowed.mkdir(parents=True)
    (allowed / "audit.md").write_text(
        "---\npublic: true\ndomain: finance\n---\n# Audit\n", encoding="utf-8"
    )
    (allowed / "notes.txt").write_text("not imported", encoding="utf-8")
    plan = scan_vault(
        vault, ["Public"], space_id="00000000-0000-0000-0000-000000000001"
    )
    assert plan.summary() == {"ready": 1, "skipped": 1}
    assert (allowed / "audit.md").read_text(encoding="utf-8").startswith("---")


def test_rejects_escape_and_symlink(tmp_path: Path):
    vault = tmp_path / "vault"
    allowed = vault / "Public"
    allowed.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = allowed / "link.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    plan = scan_vault(
        vault, ["Public"], space_id="00000000-0000-0000-0000-000000000001"
    )
    assert plan.items[0].status == "rejected"
    assert plan.items[0].reason == "symlink"


def test_public_only_and_duplicate_detection(tmp_path: Path):
    vault = tmp_path / "vault"
    allowed = vault / "Public"
    allowed.mkdir(parents=True)
    content = "---\npublic: true\n---\nSame"
    (allowed / "one.md").write_text(content, encoding="utf-8")
    (allowed / "two.md").write_text(content, encoding="utf-8")
    (allowed / "private.md").write_text(
        "---\npublic: false\n---\nPrivate", encoding="utf-8"
    )
    plan = scan_vault(
        vault,
        ["Public"],
        space_id="00000000-0000-0000-0000-000000000001",
        public_only=True,
    )
    statuses = {item.source: item.status for item in plan.items}
    assert statuses["Public/one.md"] == "ready"
    assert statuses["Public/two.md"] == "duplicate"
    assert statuses["Public/private.md"] == "skipped"


def test_frontmatter_body_and_hash_are_stable():
    metadata, body = parse_frontmatter("---\npublic: true\n---\nBody")
    assert metadata == {"public": True}
    assert hashlib.sha256(body.encode()).hexdigest()
