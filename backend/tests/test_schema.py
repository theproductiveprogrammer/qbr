from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.schemas import Brief
from src.store import OUTPUT_DIR


def _brief_paths() -> list[Path]:
    # The situation is: output/ is a cache. Under the new architecture, a
    # partially-run account directory (e.g. just corpus.json from an ingest-only
    # pass) is a legitimate state — accounts are discovered from data/input/,
    # not output/. So we test the briefs that exist, not require every output
    # subdir to have one.
    if not OUTPUT_DIR.exists():
        return []
    return [p for p in sorted(OUTPUT_DIR.glob("*/brief.json"))]


@pytest.mark.parametrize("brief_path", _brief_paths(), ids=lambda p: p.parent.name)
def test_fixture_validates(brief_path: Path) -> None:
    # The problem is: a fixture brief.json that drifts out of sync with the schema
    # would break the UI silently at runtime.
    # The way we solve this is: this parametrized test loads every brief.json under
    # output/*/ and runs it through Brief.model_validate so any drift fails loudly.
    data = json.loads(brief_path.read_text())
    Brief.model_validate(data)


def test_at_least_one_brief_exists() -> None:
    # The problem is: silent zero-fixture state would make the parametrized test
    # above pass vacuously.
    # The way we solve this is: assert at least one brief.json exists on disk so
    # CI fails when the output/ tree has no briefs to validate against.
    assert _brief_paths(), "no brief.json fixtures found under data/output/"
