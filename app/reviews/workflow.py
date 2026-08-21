from app.core.errors import AppError

TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted"}),
    "submitted": frozenset({"in_review"}),
    "in_review": frozenset({"changes_requested", "approved"}),
    "changes_requested": frozenset({"resubmitted"}),
    "resubmitted": frozenset({"in_review"}),
    "approved": frozenset({"promotion_pending"}),
    "promotion_pending": frozenset({"indexed"}),
    "indexed": frozenset({"archived"}),
    "archived": frozenset(),
}


def validate_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise AppError(
            "validation_error", f"Invalid review transition: {current} -> {target}", 422
        )
