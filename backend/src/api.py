from __future__ import annotations

import html as html_lib
import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from .config import load_pipeline_config
from .feature_catalog import CATALOG, describe_activity, describe_ownership
from .graph import PIPELINE_GRAPH
from .ingest import ACCOUNTS, INPUT_DIR, _load_aliases, _load_xlsx
from .llm import MODEL_NARRATIVE
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
    # The problem is: callers that just want a brief without streaming need a sync
    # path (CLI / tests / scripts).
    # The way we solve this is: invoke the compiled LangGraph end-to-end, then read
    # the brief.json that s5 wrote.
    # flow: callers -> POST /run -> run_account() <-- HERE -> PIPELINE_GRAPH.invoke()
    if account_id not in ACCOUNTS:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    try:
        PIPELINE_GRAPH.invoke({"account_id": account_id})
        return read_brief(account_id)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Pipeline finished but no brief.json was written")


PIPELINE_NODES = [
    "ingest",
    "extract_goals",
    "analyze_usage",
    "detect_gaps",
    "detect_opportunities",
    "generate_narrative",
]


@app.post("/accounts/{account_id}/run/stream")
async def run_stream(account_id: str):
    # The problem is: the LangGraph pipeline takes 30-90s for a real account (one
    # LLM call dominates); the user clicking Run needs to feel like something is
    # happening, not stare at a spinner.
    # The way we solve this is: SSE endpoint that streams a `start` event with the
    # known stage list, one `stage` event per node as the graph finishes it, and a
    # final `done` event carrying the full Brief so the UI re-renders without an
    # extra fetch. Errors flow through as `error` events instead of HTTP 500 so the
    # client always knows where the stream ended.
    # flow: UI Run button -> runAccountStreamed() -> POST /run/stream -> run_stream() <-- HERE
    if account_id not in ACCOUNTS:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")

    async def event_gen():
        yield _sse("start", {"account_id": account_id, "stages": PIPELINE_NODES})
        completed: list[str] = []
        try:
            async for event in PIPELINE_GRAPH.astream(
                {"account_id": account_id}, stream_mode="updates"
            ):
                for node_name in event.keys():
                    completed.append(node_name)
                    yield _sse("stage", {"node": node_name, "completed": completed})
            brief = read_brief(account_id)
            yield _sse("done", brief.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 — surface to client over SSE
            yield _sse("error", {"message": str(exc), "completed": completed})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


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
        "node": "ingest",
        "name": "Ingest",
        "description": "Parse transcripts (per-account) + load usage row from xlsx.",
        "artifact": "corpus.json",
        "is_llm": False,
        "summarize": True,
    },
    {
        "id": "s1",
        "node": "extract_goals",
        "name": "Goal extraction",
        "description": "LLM extracts customer goals with verbatim citations; pipeline links each quote back to its source turn.",
        "artifact": "goals.json",
        "trace_artifact": "s1_trace.json",
        "is_llm": True,
        "summarize": False,
    },
    {
        "id": "s2",
        "node": "analyze_usage",
        "name": "Usage analysis",
        "description": "Apply feature catalog to the account's usage row → per-feature {owned, active, signals}.",
        "artifact": "usage_facts.json",
        "is_llm": False,
        "summarize": False,
    },
    {
        "id": "s3",
        "node": "detect_gaps",
        "name": "Gap detection",
        "description": "Rules over usage × goals × catalog. Feature owned-but-inactive AND maps to a stated goal → gap.",
        "artifact": "gaps.json",
        "is_llm": False,
        "summarize": False,
    },
    {
        "id": "s4",
        "node": "detect_opportunities",
        "name": "Opportunity mapping",
        "description": "Inverse rules: feature NOT owned AND maps to a stated goal → upsell opportunity.",
        "artifact": "opportunities.json",
        "is_llm": False,
        "summarize": False,
    },
    {
        "id": "s5",
        "node": "generate_narrative",
        "name": "Narrative generation",
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
            "node": stage_def["node"],
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

    # The problem is: per-stage files only carry the evidence each stage CREATES,
    # but stages cross-reference earlier stages' evidence by id (gap.evidence_ids
    # often points to s1 quotes). Reading a stage's JSON in isolation makes those
    # references look dangling.
    # The way we solve this is: include the merged evidence map from brief.json —
    # the post-s5 union — so the Pipeline tab can resolve any evidence_id from any
    # stage without having to chain-fetch.
    merged_evidence: dict[str, Any] = {}
    brief_path = OUTPUT_DIR / account_id / "brief.json"
    if brief_path.exists():
        try:
            brief_data = json.loads(brief_path.read_text())
            merged_evidence = brief_data.get("evidence", {}) or {}
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "account_id": account_id,
        "stages": stages,
        "merged_evidence": merged_evidence,
    }


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


@app.get("/accounts/{account_id}/transcripts/{filename}", response_class=HTMLResponse)
def get_transcript_view(
    account_id: str,
    filename: str,
    cited_start: int | None = None,
    cited_end: int | None = None,
) -> HTMLResponse:
    # The problem is: the AM sees a 4-line evidence quote and wants to read 20-30
    # lines around it to judge whether the LLM picked the right moment — without
    # leaving the app to grep the file.
    # The way we solve this is: serve the full transcript as a styled HTML page
    # in a new tab. Line numbers as anchors (#L532), cited range highlighted in
    # the Podium primary blue with a brief pulse on load, auto-scrolled into
    # view. Browser ctrl+F handles search. Path-traversal-safe: we resolve and
    # check containment.
    # flow: UI EvidenceRail link click (new tab) -> GET /transcripts/{file} -> get_transcript_view() <-- HERE
    if account_id not in ACCOUNTS:
        raise HTTPException(status_code=404, detail=f"Unknown account: {account_id}")

    expected_dir = (INPUT_DIR / account_id / "transcripts").resolve()
    path = (expected_dir / filename).resolve()
    try:
        path.relative_to(expected_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename!r}")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Transcript not found: {filename!r}")

    lines = path.read_text().splitlines()
    cited_range: tuple[int, int] | None = None
    if cited_start is not None and cited_end is not None:
        cited_range = (cited_start, cited_end)

    return HTMLResponse(_render_transcript_html(filename, lines, cited_range))


_TRANSCRIPT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #f8fafc;
    --fg: #0f172a;
    --muted: #64748b;
    --primary: hsl(224 95% 58%);
    --primary-soft: hsl(224 95% 58% / 0.08);
    --primary-line: hsl(224 95% 58% / 0.45);
    --navbar: hsl(220 47% 10%);
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--fg);
    font-family: 'Inter', ui-sans-serif, system-ui, sans-serif; }}
  .navbar {{ position: sticky; top: 0; z-index: 10; background: var(--navbar); color: white;
    padding: 12px 24px; display: flex; align-items: center; gap: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.05); }}
  .brand {{ display: inline-flex; align-items: center; gap: 8px; font-size: 13px;
    font-weight: 600; letter-spacing: -0.01em; }}
  .brand-dot {{ width: 6px; height: 6px; border-radius: 2px; background: var(--primary); }}
  .filename {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px; color: rgba(255,255,255,0.7); }}
  .meta {{ margin-left: auto; font-size: 11px; color: rgba(255,255,255,0.55);
    text-transform: uppercase; letter-spacing: 0.1em; }}
  .content {{ margin: 0; padding: 20px 0 240px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px; line-height: 1.7; }}
  .line {{ display: flex; gap: 18px; padding: 0 24px; align-items: baseline; }}
  .lineno {{ user-select: none; width: 56px; text-align: right; color: var(--muted);
    font-size: 11px; text-decoration: none; flex-shrink: 0; font-variant-numeric: tabular-nums; }}
  .lineno:hover {{ color: var(--primary); }}
  .text {{ flex: 1; white-space: pre-wrap; word-break: break-word; }}
  .cited {{ background: var(--primary-soft); border-left: 3px solid var(--primary-line);
    padding-left: 21px; }}
  .cited .lineno {{ color: var(--primary); font-weight: 600; }}
  .cited:first-of-type {{ animation: pulse 1.4s ease-out 0.2s; }}
  @keyframes pulse {{
    0% {{ background: hsl(224 95% 58% / 0.28); }}
    100% {{ background: var(--primary-soft); }}
  }}
</style>
</head>
<body>
<div class="navbar">
  <span class="brand"><span class="brand-dot"></span>QBR Agent</span>
  <span class="filename">{filename}</span>
  <span class="meta">{meta}</span>
</div>
<pre class="content">{rows}</pre>
<script>
  const first = document.querySelector('.cited');
  if (first) first.scrollIntoView({{ block: 'center', behavior: 'auto' }});
</script>
</body>
</html>
"""


def _render_transcript_html(
    filename: str,
    lines: list[str],
    cited_range: tuple[int, int] | None,
) -> str:
    rows: list[str] = []
    for i, text in enumerate(lines, start=1):
        is_cited = cited_range is not None and cited_range[0] <= i <= cited_range[1]
        css = "line cited" if is_cited else "line"
        rows.append(
            f'<div class="{css}" id="L{i}">'
            f'<a class="lineno" href="#L{i}">{i}</a>'
            f'<span class="text">{html_lib.escape(text)}</span>'
            f'</div>'
        )

    if cited_range:
        s, e = cited_range
        meta = f"L{s}" if s == e else f"L{s}–{e}"
        title = f"{filename} — {meta}"
    else:
        meta = f"{len(lines)} lines"
        title = filename

    return _TRANSCRIPT_HTML.format(
        title=html_lib.escape(title),
        filename=html_lib.escape(filename),
        meta=html_lib.escape(meta),
        rows="\n".join(rows),
    )


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
            "ownership_rule": describe_ownership(f),
            "active_signal": describe_activity(f),
            "gap_message": f.gap_message,
            "recommended_action": f.recommended_action,
            "opportunity_message": f.opportunity_message,
        }
        for f in CATALOG.values()
    ]

    pipeline_config = load_pipeline_config()
    return {
        "configuration": {
            "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
            "pipeline_version": PIPELINE_VERSION,
            "models": {
                "extraction": pipeline_config.extraction_model,
                "narrative": MODEL_NARRATIVE,
            },
            "max_extraction_tokens": pipeline_config.max_extraction_tokens,
            "extraction_temperature": pipeline_config.extraction_temperature,
            "extraction_seed": pipeline_config.extraction_seed,
            "top_goals": pipeline_config.top_goals,
            "config_file": "data/pipeline.config.json",
        },
        "discovery": {
            "aliases": aliases,
            "aliases_path": "data/aliases.json",
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




if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="127.0.0.1", port=6173, reload=True)
