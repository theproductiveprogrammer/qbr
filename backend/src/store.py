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
    # The problem is: the left pane lists accounts the user can pick from. Driving
    # it off output/ meant an account that exists but hasn't been run was invisible
    # — the user couldn't open it to click Run. That's wrong: the "existence" of an
    # account is determined by its source data (data/input/<account>/), not by
    # whether the pipeline has produced artifacts yet.
    # The way we solve this is: list every account that ingest discovered (which
    # scans data/input/), then layer in run status from output/<account>/brief.json
    # (status="not_run" when absent, "failed" when the file is broken).
    # flow: UI mounts -> AccountList.useEffect -> GET /accounts -> list_accounts() <-- HERE
    from .ingest import ACCOUNTS  # lazy import — ingest imports from store
    out: list[AccountSummary] = []
    for info in sorted(ACCOUNTS.values(), key=lambda i: i.id):
        brief_path = OUTPUT_DIR / info.id / "brief.json"
        if not brief_path.exists():
            out.append(AccountSummary(
                id=info.id,
                name=info.display_name,
                vertical=info.vertical,
                status="not_run",
            ))
            continue
        try:
            brief = read_brief(info.id)
            out.append(AccountSummary(
                id=brief.account_id,
                # Prefer the discovered identity over the brief's stored values —
                # if you edit aliases.json or the xlsx, the sidebar should reflect
                # the new truth even before a re-run.
                name=info.display_name,
                vertical=info.vertical,
                status=brief.status,
                last_run_at=brief.generated_at,
            ))
        except Exception as exc:  # broken brief on disk
            out.append(AccountSummary(
                id=info.id,
                name=info.display_name,
                vertical=info.vertical,
                status="failed",
                error=f"brief.json invalid: {exc!s}",
            ))
    return out
