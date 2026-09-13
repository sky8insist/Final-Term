import pytest
from pydantic import ValidationError

from app.schemas.closure import ClosureItem, ClosureOutput


def _item(*, category: str = "uncertain") -> ClosureItem:
    return ClosureItem(
        id="c1", content="Report submission status", category=category,
        evidence="I cannot verify whether I submitted it", confidence=0.5,
        user_commitment=True,
    )


def test_uncertain_item_requires_human_confirmation():
    with pytest.raises(ValidationError, match="uncertain closure items"):
        ClosureOutput(items=[_item()], overall_summary="Status is uncertain")


def test_confirmation_ids_must_reference_extracted_items():
    with pytest.raises(ValidationError, match="must reference extracted"):
        ClosureOutput(
            items=[_item(category="unfinished")], overall_summary="Open item",
            needs_confirmation_ids=["not-an-item"],
        )


def test_uncertain_item_is_valid_when_marked_for_confirmation():
    result = ClosureOutput(
        items=[_item()], overall_summary="Status is uncertain", needs_confirmation_ids=["c1"],
    )
    assert result.needs_confirmation_ids == ["c1"]
