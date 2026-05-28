from __future__ import annotations

from typing import Any, TypedDict

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
    # The way we solve this is: a tiny state — just the account id, a flag set by
    # ingest that drives the conditional edge, and a stage-trace counter the API
    # can stream to the UI.
    account_id: str
    has_usage: bool
    stages_completed: list[str]


# ────────────────────────────── nodes ──────────────────────────────


def _bump(state: QBRState, stage_id: str) -> list[str]:
    return [*state.get("stages_completed", []), stage_id]


def node_ingest(state: QBRState) -> dict[str, Any]:
    # flow: graph START -> node_ingest <-- HERE -> conditional route
    corpus = build_corpus(state["account_id"])
    write_corpus(state["account_id"], corpus)
    return {
        "has_usage": corpus.get("usage") is not None,
        "stages_completed": _bump(state, "s0_ingest"),
    }


def node_extract_goals(state: QBRState) -> dict[str, Any]:
    out = extract_goals(state["account_id"])
    write_goals(out)
    return {"stages_completed": _bump(state, "s1_goals")}


def node_analyze_usage(state: QBRState) -> dict[str, Any]:
    out = analyze_usage(state["account_id"])
    write_usage_facts(out)
    return {"stages_completed": _bump(state, "s2_usage")}


def node_detect_gaps(state: QBRState) -> dict[str, Any]:
    out = detect_gaps(state["account_id"])
    write_gaps(out)
    return {"stages_completed": _bump(state, "s3_gaps")}


def node_detect_opportunities(state: QBRState) -> dict[str, Any]:
    out = detect_opportunities(state["account_id"])
    write_opportunities(out)
    return {"stages_completed": _bump(state, "s4_opportunities")}


def node_assemble_brief(state: QBRState) -> dict[str, Any]:
    brief = assemble_brief(state["account_id"])
    write_brief_to_disk(brief)
    return {"stages_completed": _bump(state, "s5_brief")}


# ──────────────────────────── routing ────────────────────────────


def route_after_ingest(state: QBRState) -> str:
    # The problem is: accounts with no xlsx usage row (sales leads) can't have a
    # real QBR — running s1..s4 on them produces noise.
    # The way we solve this is: branch on `has_usage` set by ingest. The "no usage"
    # path jumps straight to s5 which writes an insufficient_data brief based on
    # the corpus alone (no apex-or-anything literal in the code).
    return "extract_goals" if state.get("has_usage") else "assemble_brief"


# ─────────────────────────── compiled graph ───────────────────────────


def build_graph():
    # The problem is: stages have varying failure modes — the LLM stage can fail
    # transiently (rate limit, 5xx), but the rule stages are deterministic.
    # The way we solve this is: only the LLM-bearing node gets a RetryPolicy. Three
    # attempts with exponential backoff covers the OpenAI transient-error window
    # without burying real bugs under retries.
    g: StateGraph = StateGraph(QBRState)

    g.add_node("ingest", node_ingest)
    g.add_node(
        "extract_goals",
        node_extract_goals,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_interval=1.0,
            backoff_factor=2.0,
        ),
    )
    g.add_node("analyze_usage", node_analyze_usage)
    g.add_node("detect_gaps", node_detect_gaps)
    g.add_node("detect_opportunities", node_detect_opportunities)
    g.add_node("assemble_brief", node_assemble_brief)

    g.add_edge(START, "ingest")
    g.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {
            "extract_goals": "extract_goals",
            "assemble_brief": "assemble_brief",
        },
    )
    g.add_edge("extract_goals", "analyze_usage")
    g.add_edge("analyze_usage", "detect_gaps")
    g.add_edge("detect_gaps", "detect_opportunities")
    g.add_edge("detect_opportunities", "assemble_brief")
    g.add_edge("assemble_brief", END)

    return g.compile()


# Compile once at import — the structure is static; only state varies per run.
PIPELINE_GRAPH = build_graph()
