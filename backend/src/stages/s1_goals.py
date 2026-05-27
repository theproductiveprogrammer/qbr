from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..llm import MODEL_EXTRACTION, parse_structured
from ..schemas import Evidence, Goal, TranscriptLocator
from ..store import OUTPUT_DIR

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "goal_extract.md"

# Categories the LLM picks from. Mirrors the doctrine in the prompt — keep in sync.
GoalCategory = Literal[
    "reviews", "lead_response", "lead_integration", "call_capture",
    "messaging", "payments", "ai_adoption", "other",
]


class _ExtractedEvidence(BaseModel):
    # LLM output before the pipeline assigns a stable ev_NNN id.
    file: str = Field(description="Transcript filename, e.g. call-transcript--meridian-furniture-account-review.txt")
    line_start: int = Field(description="Starting line in the file (1-indexed, matching the transcript)")
    line_end: int = Field(description="Last content line (inclusive)")
    timestamp: str = Field(description="Timestamp as shown in the transcript, e.g. '30:21'")
    quote: str = Field(description="Verbatim customer quote — do not paraphrase")


class _ExtractedGoal(BaseModel):
    statement: str
    category: GoalCategory
    confidence: Literal["high", "med", "low"]
    evidence: list[_ExtractedEvidence] = Field(min_length=1)


class _GoalExtractionResponse(BaseModel):
    goals: list[_ExtractedGoal]


class GoalsStageOutput(BaseModel):
    # The shape we write to data/output/<account>/goals.json. Same Goal / Evidence
    # types as Brief uses, so stage 5 can splice these in directly.
    account_id: str
    goals: list[Goal]
    evidence: dict[str, Evidence]


def extract_goals(account_id: str) -> GoalsStageOutput:
    # The problem is: surfacing 1–4 real customer goals across 5–11 hour-long call
    # transcripts is the bottleneck of QBR prep — and a hallucinated goal in front of
    # the customer is worse than no goal at all.
    # The way we solve this is: serialize every speaker turn with its line+timestamp
    # locator, send to the model with a strict pydantic schema that forces verbatim
    # quoting, then re-validate the citations against the corpus before persisting.
    # flow: pipeline.run_pipeline() -> extract_goals() <-- HERE -> OpenAI -> write_goals()
    corpus = _load_corpus(account_id)
    user_content = _format_corpus_for_prompt(corpus)
    system_prompt = PROMPT_PATH.read_text()

    response = parse_structured(
        model=MODEL_EXTRACTION,
        system_prompt=system_prompt,
        user_content=user_content,
        response_format=_GoalExtractionResponse,
    )

    return _assign_ids(account_id, response.goals)


def write_goals(stage_out: GoalsStageOutput) -> Path:
    # The problem is: a half-written goals.json read by a re-run mid-pipeline would
    # poison stage 5's brief assembly.
    # The way we solve this is: temp-write + atomic rename, matching store.write_brief.
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
    # Render every transcript as a sequence of line-anchored turns so the model can
    # cite line numbers verbatim. File headers separate transcripts so the model never
    # confuses which file a quote came from.
    blocks: list[str] = [
        f"Account: {corpus['account_name']} ({corpus['vertical']})",
        f"Total transcripts: {len(corpus['transcripts'])}",
        "",
    ]
    for t in corpus["transcripts"]:
        blocks.append(f"--- FILE: {t['file']} ---")
        for turn in t["turns"]:
            blocks.append(
                f"L{turn['line_start']}-{turn['line_end']} @ {turn['timestamp']} | "
                f"{turn['speaker']}: {turn['text']}"
            )
        blocks.append("")
    return "\n".join(blocks)


def _assign_ids(account_id: str, extracted: list[_ExtractedGoal]) -> GoalsStageOutput:
    # The problem is: the LLM emits goals with embedded evidence but no stable IDs;
    # the brief.json schema expects every goal to reference evidence by id.
    # The way we solve this is: walk the extraction in order, assign g_NNN to each
    # goal and ev_NNN to each unique (file, line_start, line_end) tuple — same
    # quote cited by two goals collapses to one evidence record.
    goals: list[Goal] = []
    evidence: dict[str, Evidence] = {}
    seen: dict[tuple[str, int, int], str] = {}

    for g_idx, g in enumerate(extracted, start=1):
        evidence_ids: list[str] = []
        for ev in g.evidence:
            key = (ev.file, ev.line_start, ev.line_end)
            if key in seen:
                evidence_ids.append(seen[key])
                continue
            ev_id = f"ev_{len(evidence) + 1:03d}"
            seen[key] = ev_id
            evidence_ids.append(ev_id)
            evidence[ev_id] = Evidence(
                id=ev_id,
                source="transcript",
                locator=TranscriptLocator(
                    kind="transcript",
                    file=ev.file,
                    line_start=ev.line_start,
                    line_end=ev.line_end,
                    timestamp=ev.timestamp,
                ),
                quote=ev.quote,
            )

        goals.append(Goal(
            id=f"g_{g_idx:03d}",
            statement=g.statement,
            category=g.category,
            confidence=g.confidence,
            evidence_ids=evidence_ids,
        ))

    return GoalsStageOutput(account_id=account_id, goals=goals, evidence=evidence)
