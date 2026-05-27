from __future__ import annotations

import json
from pathlib import Path

from .schemas import AccountSummary, Brief

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"


def read_brief(account_id: str) -> Brief:
    # The problem is: every endpoint that returns a brief must enforce its schema so
    # the UI never receives broken JSON.
    # The way we solve this is: load the file then run it through pydantic validation,
    # so failures raise loudly here rather than silently downstream.
    # flow: GET /accounts/{id}/brief -> api.get_brief -> read_brief() <-- HERE
    path = OUTPUT_DIR / account_id / "brief.json"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as f:
        data = json.load(f)
    return Brief.model_validate(data)


def write_brief(account_id: str, brief: Brief) -> None:
    # The problem is: a partially-written brief.json read by the UI mid-pipeline would
    # render garbage state.
    # The way we solve this is: write to a sibling temp file, then atomic rename so the
    # UI either sees the old brief or the new one, never a half-file.
    # flow: pipeline final stage completes -> graph emits state -> write_brief() <-- HERE
    path = OUTPUT_DIR / account_id / "brief.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        f.write(brief.model_dump_json(indent=2))
    tmp.replace(path)


def list_accounts() -> list[AccountSummary]:
    # The problem is: the UI's left pane needs a lightweight summary per account
    # without loading every pipeline artifact.
    # The way we solve this is: scan output/ for subdirs, peek at each brief.json
    # (or mark "not run" if absent), return the minimal projection the UI needs.
    # flow: UI mounts -> AccountList.useEffect -> GET /accounts -> list_accounts() <-- HERE
    if not OUTPUT_DIR.exists():
        return []
    out: list[AccountSummary] = []
    for account_dir in sorted(OUTPUT_DIR.iterdir()):
        if not account_dir.is_dir():
            continue
        brief_path = account_dir / "brief.json"
        if not brief_path.exists():
            out.append(AccountSummary(
                id=account_dir.name,
                name=account_dir.name,
                vertical="(unknown)",
                status="not_run",
            ))
            continue
        try:
            brief = read_brief(account_dir.name)
            out.append(AccountSummary(
                id=brief.account_id,
                name=brief.account_name,
                vertical=brief.vertical,
                status=brief.status,
                last_run_at=brief.generated_at,
            ))
        except Exception as exc:  # broken fixture
            out.append(AccountSummary(
                id=account_dir.name,
                name=account_dir.name,
                vertical="(unknown)",
                status="failed",
                error=f"brief.json invalid: {exc!s}",
            ))
    return out
