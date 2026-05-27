from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.schemas import Brief
from src.store import OUTPUT_DIR


def _account_dirs() -> list[Path]:
    if not OUTPUT_DIR.exists():
        return []
    return [d for d in sorted(OUTPUT_DIR.iterdir()) if d.is_dir()]


@pytest.mark.parametrize("account_dir", _account_dirs(), ids=lambda d: d.name)
def test_fixture_validates(account_dir: Path) -> None:
    # The problem is: a fixture brief.json that drifts out of sync with the schema
    # would break the UI silently at runtime.
    # The way we solve this is: this parametrized test loads every fixture under
    # output/ and runs it through Brief.model_validate so any drift fails CI loudly.
    brief_path = account_dir / "brief.json"
    assert brief_path.exists(), f"missing fixture: {brief_path}"
    data = json.loads(brief_path.read_text())
    Brief.model_validate(data)


def test_at_least_one_fixture_exists() -> None:
    # The problem is: silent zero-fixture state would make the parametrized test
    # above pass vacuously.
    # The way we solve this is: assert at least one fixture exists, so CI fails
    # when the output/ tree is empty.
    assert _account_dirs(), "no fixtures found under backend/output/"
