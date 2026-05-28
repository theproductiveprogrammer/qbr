from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .feature_catalog import CATALOG, Feature
from .ingest import ACCOUNTS, INPUT_DIR, _load_aliases, _load_xlsx
from .llm import MODEL_EXTRACTION, MODEL_NARRATIVE
from .schemas import AccountSummary, Brief
from .stages.s5_brief import PIPELINE_VERSION
from .store import OUTPUT_DIR, list_accounts, read_brief

app = FastAPI(title="QBR Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/accounts", response_model=list[AccountSummary])
def get_accounts() -> list[AccountSummary]:
    # The problem is: the left pane needs to list which accounts exist and their run
    # status so the user can pick one.
    # The way we solve this is: scan output/ for per-account brief.json files and
    # project them into AccountSummary records.
    # flow: UI mounts -> AccountList.useEffect -> GET /accounts -> get_accounts() <-- HERE
    return list_accounts()


@app.post("/accounts/{account_id}/run", response_model=Brief)
def run_account(account_id: str) -> Brief:
    # The problem is: clicking Run needs to trigger the pipeline and block until the
    # brief is ready for render.
    # The way we solve this is: scaffold returns the existing fixture; once the
    # LangGraph pipeline lands this will invoke it synchronously and write the result.
    # flow: UI Run button -> RunButton.onClick -> POST /run -> run_account() <-- HERE
    # TODO: replace stub with graph.run(account_id) once src/graph.py exists
    try:
        return read_brief(account_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")


@app.get("/accounts/{account_id}/brief", response_model=Brief)
def get_brief(account_id: str) -> Brief:
    # The problem is: re-opening an already-run account in the UI needs to hydrate
    # the results pane without re-running the pipeline.
    # The way we solve this is: read brief.json from disk and validate it against the
    # schema before returning, so the UI is guaranteed a well-formed payload.
    # flow: UI account-select -> ResultsPane.useEffect -> GET /brief -> get_brief() <-- HERE
    try:
        return read_brief(account_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No brief found for '{account_id}'")


PIPELINE_STAGES = [
    {
        "id": "s0",
        "name": "Ingest",
        "description": "Parse transcripts (per-account) + load usage row from xlsx.",
        "artifact": "corpus.json",
        "is_llm": False,
        "summarize": True,
    },
    {
        "id": "s1",
        "name": "Goal extraction",
        "description": "LLM extracts customer goals with verbatim citations; pipeline links each quote back to its source turn.",
        "artifact": "goals.json",
        "trace_artifact": "s1_trace.json",
        "is_llm": True,
        "summarize": False,
    },
    {
        "id": "s2",
        "name": "Usage analysis",
        "description": "Apply feature catalog to the account's usage row → per-feature {owned, active, signals}.",
        "artifact": "usage_facts.json",
        "is_llm": False,
        "summarize": False,
    },
    {
        "id": "s3",
        "name": "Gap detection",
        "description": "Rules over usage × goals × catalog. Feature owned-but-inactive AND maps to a stated goal → gap.",
        "artifact": "gaps.json",
        "is_llm": False,
        "summarize": False,
    },
    {
        "id": "s4",
        "name": "Opportunity mapping",
        "description": "Inverse rules: feature NOT owned AND maps to a stated goal → upsell opportunity.",
        "artifact": "opportunities.json",
        "is_llm": False,
        "summarize": False,
    },
    {
        "id": "s5",
        "name": "Brief assembly",
        "description": "Compose goals + working + gaps + opportunities + evidence into the final brief.json the UI renders.",
        "artifact": "brief.json",
        "is_llm": False,
        "summarize": False,
    },
]


@app.get("/accounts/{account_id}/pipeline")
def get_pipeline(account_id: str) -> dict[str, Any]:
    # The problem is: reviewers (and the AM) want to see what the agent actually did —
    # which stages ran, what each stage emitted, and for LLM stages what was sent and
    # received. Without this view, the pipeline is a black box producing a brief.
    # The way we solve this is: read every per-stage artifact from disk and return
    # them in one bundle. Corpus is summarized (turns elided) because it's huge and
    # the per-turn data isn't useful in a debug view.
    # flow: UI Pipeline tab -> PipelinePane.useEffect -> GET /pipeline -> get_pipeline() <-- HERE
    stages: list[dict[str, Any]] = []
    for stage_def in PIPELINE_STAGES:
        artifact_path = OUTPUT_DIR / account_id / stage_def["artifact"]
        entry: dict[str, Any] = {
            "id": stage_def["id"],
            "name": stage_def["name"],
            "description": stage_def["description"],
            "artifact": stage_def["artifact"],
            "is_llm": stage_def["is_llm"],
            "status": "missing",
            "data": None,
            "trace": None,
        }
        if artifact_path.exists():
            entry["status"] = "ok"
            data = json.loads(artifact_path.read_text())
            entry["data"] = _summarize_corpus(data) if stage_def.get("summarize") else data
        trace_name = stage_def.get("trace_artifact")
        if trace_name:
            trace_path = OUTPUT_DIR / account_id / trace_name
            if trace_path.exists():
                entry["trace"] = json.loads(trace_path.read_text())
        stages.append(entry)
    return {"account_id": account_id, "stages": stages}


def _summarize_corpus(data: dict[str, Any]) -> dict[str, Any]:
    # The problem is: corpus.json is hundreds of KB (every turn from every transcript)
    # and rendering it raw in the UI is overwhelming and useless.
    # The way we solve this is: project to a summary — per-transcript metadata + the
    # usage-column key list — so the Pipeline tab shows shape and counts, not noise.
    return {
        "account_id": data.get("account_id"),
        "account_name": data.get("account_name"),
        "vertical": data.get("vertical"),
        "transcripts": [
            {
                "file": t.get("file"),
                "recorded_date": t.get("recorded_date"),
                "n_lines": t.get("n_lines"),
                "n_turns": len(t.get("turns", [])),
            }
            for t in data.get("transcripts", [])
        ],
        "n_emails": len(data.get("emails", [])),
        "usage_columns_present": (
            len(data["usage"]) if isinstance(data.get("usage"), dict) else 0
        ),
    }


@app.get("/settings")
def get_settings() -> dict[str, Any]:
    # The problem is: a reviewer (and the AM) needs to see what configuration the
    # pipeline is running on — the alias mapping, what got resolved against the xlsx,
    # which features the agent knows about, which models are wired up, and whether
    # OPENAI_API_KEY is set — without grepping the filesystem.
    # The way we solve this is: one bundled snapshot read at request time. None of
    # this is secret; we expose the PRESENCE of OPENAI_API_KEY, never the value.
    # flow: UI Settings tab -> SettingsPane.useEffect -> GET /settings -> get_settings() <-- HERE
    aliases = _load_aliases()
    xlsx_path = INPUT_DIR / "accounts.xlsx"
    xlsx_present = xlsx_path.exists()

    accounts_payload: list[dict[str, Any]] = []
    for info in sorted(ACCOUNTS.values(), key=lambda i: i.id):
        account_dir = INPUT_DIR / info.id
        transcripts_dir = account_dir / "transcripts"
        emails_dir = account_dir / "emails"
        accounts_payload.append({
            "id": info.id,
            "display_name": info.display_name,
            "vertical": info.vertical,
            "xlsx_org_name": info.xlsx_org_name,
            "is_lead": info.xlsx_org_name is None,
            "transcript_count": (
                len(list(transcripts_dir.glob("*.txt"))) if transcripts_dir.exists() else 0
            ),
            "email_count": (
                len(list(emails_dir.glob("*.eml"))) if emails_dir.exists() else 0
            ),
        })

    feature_payload: list[dict[str, Any]] = [
        {
            "id": f.id,
            "label": f.label,
            "goal_categories": f.goal_categories,
            "ownership_rule": _describe_ownership(f),
            "active_signal": _describe_activity(f),
        }
        for f in CATALOG.values()
    ]

    return {
        "configuration": {
            "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
            "pipeline_version": PIPELINE_VERSION,
            "models": {
                "extraction": MODEL_EXTRACTION,
                "narrative": MODEL_NARRATIVE,
            },
        },
        "discovery": {
            "aliases": aliases,
            "aliases_path": "data/input/aliases.json",
            "xlsx": {
                "path": "data/input/accounts.xlsx",
                "exists": xlsx_present,
                "row_count": len(_load_xlsx()) if xlsx_present else 0,
            },
            "accounts": accounts_payload,
        },
        "feature_catalog": feature_payload,
        "data_paths": {
            "input": "data/input/",
            "output": "data/output/",
        },
    }


def _describe_ownership(f: Feature) -> str:
    if f.ownership_rule == "always":
        return "always owned (built-in)"
    col = f.ownership_col or "(unset)"
    if f.ownership_rule == "contains":
        return f'{col} contains "{f.ownership_value}"'
    if f.ownership_rule == "equals":
        return f'{col} == "{f.ownership_value}"'
    if f.ownership_rule == "gt_0":
        return f"{col} > 0"
    if f.ownership_rule == "any_lifetime":
        return f"{col} ever > 0"
    return f.ownership_rule


def _describe_activity(f: Feature) -> str:
    if f.active_col is None:
        return "(no signal defined)"
    return f"{f.active_col} ≥ {f.active_threshold:g}"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=6173, reload=True)
