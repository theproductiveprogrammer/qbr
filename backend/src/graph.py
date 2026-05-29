from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from .ingest import build_corpus, write_corpus
from .stages.s1_goals import extract_goals, write_goals
from .stages.s2_usage import analyze_usage, write_usage_facts
from .stages.s3_gaps import detect_gaps, write_gaps
from .stages.s4_opportunities import detect_opportunities, write_opportunities
from .stages.s5_brief import assemble_brief, write_brief_to_disk


class QBRState(TypedDict, total=False):
    # The problem is: LangGraph's state must be a TypedDict (or pydantic model). We
    # don't want to serialize huge artifacts into the state — each stage already
    # writes its own JSON file to disk and reads what it needs from earlier stages.
    # Also: s1 and s2 run in parallel, so two nodes may write `stages_completed`
    # concurrently — without a reducer LangGraph would clobber one update with
    # the other.
    # The way we solve this is: a tiny state — account id, a flag set by ingest
    # that drives the conditional edge, and a stages_completed list with an
    # `operator.add` reducer so parallel-stage completions append cleanly.
    # Each node returns ONLY its own stage_id; the reducer does the appending.
    account_id: str
    has_usage: bool
    stages_completed: Annotated[list[str], add]


# ────────────────────────────── nodes ──────────────────────────────


def node_ingest(state: QBRState) -> dict[str, Any]:
    # flow: graph START -> node_ingest <-- HERE -> conditional route (fans out)
    corpus = build_corpus(state["account_id"])
    write_corpus(state["account_id"], corpus)
    return {
        "has_usage": corpus.get("usage") is not None,
        "stages_completed": ["s0_ingest"],
    }


def node_extract_goals(state: QBRState) -> dict[str, Any]:
    out = extract_goals(state["account_id"])
    write_goals(out)
    return {"stages_completed": ["s1_goals"]}


def node_analyze_usage(state: QBRState) -> dict[str, Any]:
    out = analyze_usage(state["account_id"])
    write_usage_facts(out)
    return {"stages_completed": ["s2_usage"]}


def node_detect_gaps(state: QBRState) -> dict[str, Any]:
    out = detect_gaps(state["account_id"])
    write_gaps(out)
    return {"stages_completed": ["s3_gaps"]}


def node_detect_opportunities(state: QBRState) -> dict[str, Any]:
    out = detect_opportunities(state["account_id"])
    write_opportunities(out)
    return {"stages_completed": ["s4_opportunities"]}


def node_generate_narrative(state: QBRState) -> dict[str, Any]:
    brief = assemble_brief(state["account_id"])
    write_brief_to_disk(brief)
    return {"stages_completed": ["s5_narrative"]}


# ──────────────────────────── routing ────────────────────────────


def route_after_ingest(state: QBRState) -> list[str] | str:
    # The problem is: accounts with no xlsx usage row (sales leads) can't have a
    # real QBR — running s1..s4 on them produces noise. For real customers, s1
    # (transcripts → LLM) and s2 (usage row → pandas) have no dependency on
    # each other, so they should run concurrently.
    # The way we solve this is: branch on `has_usage`. The "yes" path fans out
    # to BOTH extract_goals AND analyze_usage as a list — LangGraph runs them in
    # parallel and the join at detect_gaps waits for both. The "no" path jumps
    # straight to generate_narrative which writes an insufficient_data brief.
    if state.get("has_usage"):
        return ["extract_goals", "analyze_usage"]
    return "generate_narrative"


# ─────────────────────────── compiled graph ───────────────────────────


def build_graph():
    # The problem is: stages have varying failure modes — the LLM stages (s1
    # extraction, s5 narration) can fail transiently (rate limit, 5xx), but the
    # rule stages are deterministic. And s1 / s2 are independent and should run
    # concurrently.
    # The way we solve this is: only the LLM-bearing nodes get a RetryPolicy
    # (three attempts, exponential backoff). The conditional edge from ingest
    # fans out s1 + s2 in parallel; detect_gaps waits on both inputs (LangGraph
    # join semantics).
    g: StateGraph = StateGraph(QBRState)

    llm_retry = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0)

    g.add_node("ingest", node_ingest)
    g.add_node("extract_goals", node_extract_goals, retry_policy=llm_retry)
    g.add_node("analyze_usage", node_analyze_usage)
    g.add_node("detect_gaps", node_detect_gaps)
    g.add_node("detect_opportunities", node_detect_opportunities)
    g.add_node("generate_narrative", node_generate_narrative, retry_policy=llm_retry)

    g.add_edge(START, "ingest")
    g.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {
            # Mapping is per RETURN-VALUE-ITEM. When route_after_ingest returns
            # the list ["extract_goals", "analyze_usage"], LangGraph triggers
            # both in parallel.
            "extract_goals": "extract_goals",
            "analyze_usage": "analyze_usage",
            "generate_narrative": "generate_narrative",
        },
    )
    # s1 and s2 both feed detect_gaps; LangGraph joins (waits for all upstreams).
    g.add_edge("extract_goals", "detect_gaps")
    g.add_edge("analyze_usage", "detect_gaps")
    g.add_edge("detect_gaps", "detect_opportunities")
    g.add_edge("detect_opportunities", "generate_narrative")
    g.add_edge("generate_narrative", END)

    return g.compile()


# Compile once at import — the structure is static; only state varies per run.
PIPELINE_GRAPH = build_graph()
