from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..linking import link_quote
from ..llm import MODEL_EXTRACTION, parse_structured
from ..schemas import Evidence, Goal
from ..store import OUTPUT_DIR

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "goal_extract.md"

# Categories the LLM picks from. Mirrors the doctrine in the prompt — keep in sync.
GoalCategory = Literal[
    "reviews", "lead_response", "lead_integration", "call_capture",
    "messaging", "payments", "ai_adoption", "other",
]


class _ExtractedEvidence(BaseModel):
    # LLM emits only (file, quote). The pipeline links the quote back to a parsed
    # turn to recover line range + timestamp — this is the hallucination filter.
    file: str = Field(description="Transcript filename, copied from a `=== FILE: ... ===` header")
    quote: str = Field(description="Verbatim customer quote, character-for-character from the transcript")


class _ExtractedGoal(BaseModel):
    statement: str
    category: GoalCategory
    confidence: Literal["high", "med", "low"]
    evidence: list[_ExtractedEvidence] = Field(min_length=1)


class _GoalExtractionResponse(BaseModel):
    goals: list[_ExtractedGoal]


class GoalsStageOutput(BaseModel):
    # The shape written to data/output/<account>/goals.json. Same Goal / Evidence
    # types as Brief uses, so stage 5 can splice these in directly.
    account_id: str
    goals: list[Goal]
    evidence: dict[str, Evidence]
    warnings: list[str] = Field(default_factory=list)


def extract_goals(account_id: str) -> GoalsStageOutput:
    # The problem is: surfacing 1–4 real customer goals across 5–11 hour-long
    # transcripts is the bottleneck of QBR prep, and a hallucinated goal in front of
    # the customer is worse than no goal at all.
    # The way we solve this is: send transcripts in their native shape, ask the LLM
    # for verbatim customer quotes only, then deterministically link each quote back
    # to its parsed turn to recover line numbers (or drop it as hallucinated).
    # flow: pipeline.run_pipeline() -> extract_goals() <-- HERE -> OpenAI -> link -> write
    corpus = _load_corpus(account_id)
    user_content = _format_corpus_for_prompt(corpus)
    system_prompt = PROMPT_PATH.read_text()

    response = parse_structured(
        model=MODEL_EXTRACTION,
        system_prompt=system_prompt,
        user_content=user_content,
        response_format=_GoalExtractionResponse,
    )

    # Persist the LLM trace so the Pipeline tab can show exactly what was sent and
    # what came back — separately from the linked-and-validated goals.json.
    _write_trace(account_id, system_prompt, user_content, response)

    return _link_and_assign_ids(account_id, response.goals, corpus)


def _write_trace(
    account_id: str,
    system_prompt: str,
    user_content: str,
    response: "_GoalExtractionResponse",
) -> None:
    # The problem is: the Pipeline tab needs to surface what the LLM was asked and
    # what it returned BEFORE pipeline post-processing — so a reviewer can audit the
    # extraction quality, not just the final filtered output.
    # The way we solve this is: write a sibling s1_trace.json carrying the system
    # prompt, the rendered user prompt, the model id, and the raw structured response.
    trace = {
        "stage": "s1_goals",
        "model": MODEL_EXTRACTION,
        "system_prompt": system_prompt,
        "user_prompt": user_content,
        "user_prompt_chars": len(user_content),
        "raw_response": response.model_dump(),
    }
    path = OUTPUT_DIR / account_id / "s1_trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(trace, indent=2))
    tmp.replace(path)


def write_goals(stage_out: GoalsStageOutput) -> Path:
    # flow: pipeline.run_pipeline() -> extract_goals() -> write_goals() <-- HERE
    path = OUTPUT_DIR / stage_out.account_id / "goals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(stage_out.model_dump_json(indent=2))
    tmp.replace(path)
    return path


def _load_corpus(account_id: str) -> dict[str, Any]:
    corpus_path = OUTPUT_DIR / account_id / "corpus.json"
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"No corpus.json for '{account_id}'. Run ingest first: "
            f"mise run pipeline -- --account {account_id} --only ingest"
        )
    return json.loads(corpus_path.read_text())


def _format_corpus_for_prompt(corpus: dict[str, Any]) -> str:
    # Render each transcript in its native `MM:SS | Speaker\ncontent` shape and each
    # email thread in its native `From:/Date:/Subject:` + body shape. File separators
    # double as the value the LLM emits in evidence.file.
    n_transcripts = len(corpus.get("transcripts", []))
    n_emails = len(corpus.get("emails", []))
    blocks: list[str] = [
        f"Account: {corpus['account_name']} ({corpus['vertical']})",
        f"Sources: {n_transcripts} transcript(s), {n_emails} email thread(s)",
        "",
    ]
    for t in corpus.get("transcripts", []):
        blocks.append(f"=== FILE: {t['file']} ===")
        if t.get("recorded_date"):
            blocks.append(f"Date: {t['recorded_date']}")
        blocks.append("")
        for turn in t["turns"]:
            blocks.append(f"{turn['timestamp']} | {turn['speaker']}")
            blocks.append(turn["text"])
            blocks.append("")
    for e in corpus.get("emails", []):
        blocks.append(f"=== FILE: {e['file']} ===")
        blocks.append("")
        for msg in e["messages"]:
            blocks.append(f"From: {msg['sender']}")
            blocks.append(f"Date: {msg['date']}")
            blocks.append(f"Subject: {msg['subject']}")
            blocks.append("")
            blocks.append(msg["body"])
            blocks.append("")
            blocks.append("---")
            blocks.append("")
    return "\n".join(blocks)


def _link_and_assign_ids(
    account_id: str,
    extracted: list[_ExtractedGoal],
    corpus: dict[str, Any],
) -> GoalsStageOutput:
    # The problem is: the LLM emits goals with quotes but no IDs and no source
    # locators; before persisting we need stable g_NNN / ev_NNN IDs AND we need to
    # verify each quote exists in its named transcript.
    # The way we solve this is: walk goals in order, link each evidence quote via
    # the deterministic linker, drop unlinked quotes as hallucinations (with a
    # warning), drop goals whose entire evidence set fails to link.
    goals: list[Goal] = []
    evidence: dict[str, Evidence] = {}
    warnings: list[str] = []
    # Same (file, line_start, line_end) tuple cited twice reuses one ev_NNN.
    seen: dict[tuple[str, int, int], str] = {}

    for g in extracted:
        evidence_ids: list[str] = []
        for ev in g.evidence:
            locator = link_quote(ev.quote, ev.file, corpus)
            if locator is None:
                warnings.append(
                    f"unlinked quote in {ev.file!r} for goal {g.statement!r}: "
                    f"{ev.quote[:120]!r}"
                )
                continue
            key = (locator.file, locator.line_start, locator.line_end)
            if key in seen:
                evidence_ids.append(seen[key])
                continue
            ev_id = f"ev_{len(evidence) + 1:03d}"
            seen[key] = ev_id
            evidence_ids.append(ev_id)
            evidence[ev_id] = Evidence(
                id=ev_id,
                source="transcript",
                locator=locator,
                quote=ev.quote,
            )

        if not evidence_ids:
            warnings.append(
                f"goal dropped (all {len(g.evidence)} evidence quote(s) unlinked): "
                f"{g.statement!r}"
            )
            continue

        goals.append(Goal(
            id=f"g_{len(goals) + 1:03d}",
            statement=g.statement,
            category=g.category,
            confidence=g.confidence,
            evidence_ids=evidence_ids,
        ))

    return GoalsStageOutput(
        account_id=account_id,
        goals=goals,
        evidence=evidence,
        warnings=warnings,
    )
