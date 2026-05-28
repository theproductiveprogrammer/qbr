from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import load_pipeline_config
from ..linking import link_quote
from ..llm import parse_structured
from ..schemas import Evidence, Goal, TranscriptLocator
from ..store import OUTPUT_DIR

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "goal_extract.md"

GoalCategory = Literal[
    "reviews", "lead_response", "lead_integration", "call_capture",
    "messaging", "payments", "ai_adoption", "other",
]

def _render_prompt(template: str, top_goals: int) -> str:
    # The problem is: the prompt body and the code's post-dedup cap have to
    # agree on the same N. Hardcoding "4" in both places meant changing it took
    # two edits and drift was easy.
    # The way we solve this is: the prompt file ships with {{TOP_GOALS}} /
    # {{TOP_GOALS_PLUS_ONE}} placeholders that this function substitutes at
    # runtime using pipeline.config.json's top_goals. One number, one source.
    # flow: extract_goals() -> _render_prompt() <-- HERE
    return (
        template
        .replace("{{TOP_GOALS}}", str(top_goals))
        .replace("{{TOP_GOALS_PLUS_ONE}}", str(top_goals + 1))
    )


class _ExtractedEvidence(BaseModel):
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
    account_id: str
    goals: list[Goal]
    evidence: dict[str, Evidence]
    warnings: list[str] = Field(default_factory=list)


def extract_goals(account_id: str) -> GoalsStageOutput:
    # The problem is: surfacing 1–4 real customer goals across N hour-long
    # transcripts is the bottleneck of QBR prep, AND once N is large enough the
    # whole corpus stops fitting in one LLM call.
    # The way we solve this is: greedy token-budget batching of transcripts
    # (chronological order preserved), per-batch extraction with the same strict
    # prompt, cross-batch semantic dedup by category + statement-token similarity,
    # final top-K cap. Single-batch accounts behave identically to the pre-batching
    # implementation.
    # flow: pipeline.run_pipeline() -> extract_goals() <-- HERE -> OpenAI x N -> dedup -> link
    corpus = _load_corpus(account_id)
    config = load_pipeline_config()
    batches = _batch_transcripts(corpus.get("transcripts", []), config.max_extraction_tokens)
    system_prompt = _render_prompt(PROMPT_PATH.read_text(), config.top_goals)

    all_raw_goals: list[_ExtractedGoal] = []
    batch_traces: list[dict[str, Any]] = []

    for batch_idx, batch_transcripts in enumerate(batches):
        # Build a sub-corpus containing only this batch's transcripts. Emails are
        # included in every batch for now (they're typically tiny relative to
        # transcripts); switch to email batching when real email data lands.
        batch_corpus = {**corpus, "transcripts": batch_transcripts}
        user_content = _format_corpus_for_prompt(batch_corpus)

        response = parse_structured(
            model=config.extraction_model,
            system_prompt=system_prompt,
            user_content=user_content,
            response_format=_GoalExtractionResponse,
            temperature=config.extraction_temperature,
            seed=config.extraction_seed,
        )

        all_raw_goals.extend(response.goals)
        batch_traces.append({
            "batch_index": batch_idx,
            "transcripts": [t["file"] for t in batch_transcripts],
            "user_prompt": user_content,
            "user_prompt_chars": len(user_content),
            "n_goals_emitted": len(response.goals),
            "raw_response": response.model_dump(),
        })

    # Dedup across batches, then cap. For single-batch accounts this is a no-op
    # unless the LLM emits duplicates within the batch (rare with the prompt).
    deduped = _dedupe_goals(all_raw_goals)
    capped = _cap_goals(deduped, config.top_goals)

    _write_trace(account_id, system_prompt, batches, batch_traces, all_raw_goals, capped)
    return _link_and_assign_ids(account_id, capped, corpus)


# ────────────────────────── batching ──────────────────────────


def _estimate_transcript_tokens(transcript: dict[str, Any]) -> int:
    # Rough char-based estimate (~4 chars/token for English). Overestimating
    # leads to smaller batches than necessary, never a context overflow.
    total = 0
    for turn in transcript.get("turns", []):
        total += len(turn.get("text", "")) + len(turn.get("speaker", "")) + 10  # header overhead per turn
    return total // 4 + 200  # +200 for the FILE/Date headers


def _batch_transcripts(
    transcripts: list[dict[str, Any]],
    max_tokens: int,
) -> list[list[dict[str, Any]]]:
    # The problem is: a single LLM call has a finite context. Accounts with many
    # long transcripts need to be split, but chronological order matters for the
    # LLM's read of the relationship arc.
    # The way we solve this is: greedy fill — keep adding the next transcript to
    # the current batch until it would exceed the budget, then start a new batch.
    # Always pack at least one transcript per batch even if it exceeds the budget
    # alone (the model can still process it; we just can't split it further
    # without losing per-transcript context).
    if not transcripts:
        return []
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for t in transcripts:
        t_tokens = _estimate_transcript_tokens(t)
        if current and current_tokens + t_tokens > max_tokens:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(t)
        current_tokens += t_tokens
    if current:
        batches.append(current)
    return batches


# ────────────────────────── dedup ──────────────────────────


def _confidence_rank(c: str) -> int:
    return {"high": 3, "med": 2, "low": 1}.get(c, 0)


def _merge_cluster(cluster: list[_ExtractedGoal]) -> _ExtractedGoal:
    # Pick the longest statement (usually most specific), combine all evidence
    # (deduped by file+quote-prefix), take the strongest confidence.
    longest = max(cluster, key=lambda g: len(g.statement))
    merged_evidence: list[_ExtractedEvidence] = []
    seen: set[tuple[str, str]] = set()
    for g in cluster:
        for ev in g.evidence:
            key = (ev.file, ev.quote[:60].lower())
            if key in seen:
                continue
            seen.add(key)
            merged_evidence.append(ev)
    best_conf = max((g.confidence for g in cluster), key=_confidence_rank)
    return _ExtractedGoal(
        statement=longest.statement,
        category=longest.category,
        confidence=best_conf,  # type: ignore[arg-type]
        evidence=merged_evidence,
    )


def _dedupe_goals(goals: list[_ExtractedGoal]) -> list[_ExtractedGoal]:
    # The problem is: per-batch extraction can emit the same conceptual goal
    # multiple times (different wording, same intent), especially when a goal
    # persists across the customer's lifecycle and surfaces in different batches.
    # The way we solve this is: dedupe by CATEGORY. Categories are the controlled
    # vocabulary that maps to features in the catalog — two goals in the same
    # category map to the same downstream recommendations, so consolidating them
    # into one canonical goal (longest statement wins, all evidence preserved) is
    # the right semantics for a QBR brief.
    if len(goals) <= 1:
        return list(goals)
    by_category: dict[str, list[_ExtractedGoal]] = defaultdict(list)
    for g in goals:
        by_category[g.category].append(g)
    return [_merge_cluster(cluster) for cluster in by_category.values()]


def _cap_goals(goals: list[_ExtractedGoal], cap: int) -> list[_ExtractedGoal]:
    # If multi-batch + conservative dedup leaves us with more than the cap, rank
    # by (confidence × 10 + evidence_count) and take top K. Single-batch accounts
    # with ≤ cap goals pass through untouched.
    if len(goals) <= cap:
        return goals
    scored = sorted(
        goals,
        key=lambda g: (_confidence_rank(g.confidence) * 10 + len(g.evidence)),
        reverse=True,
    )
    return scored[:cap]


# ────────────────────────── trace + write ──────────────────────────


def _write_trace(
    account_id: str,
    system_prompt: str,
    batches: list[list[dict[str, Any]]],
    batch_traces: list[dict[str, Any]],
    all_raw_goals: list[_ExtractedGoal],
    capped: list[_ExtractedGoal],
) -> None:
    # Persisted trace now reflects multi-batch reality: each batch has its own
    # rendered prompt + raw response, plus a top-level "after_dedup_and_cap" view
    # of what actually fed into linking.
    trace = {
        "stage": "s1_goals",
        "model": load_pipeline_config().extraction_model,
        "system_prompt": system_prompt,
        "n_batches": len(batches),
        "batches": batch_traces,
        "n_goals_before_dedup": len(all_raw_goals),
        "n_goals_after_dedup_and_cap": len(capped),
        # Convenience aliases for the existing Pipeline-tab UI — first batch's
        # prompt/response render as the "default" view when there's only one. For
        # multi-batch runs the UI can scan `batches` to show per-batch details.
        "user_prompt": batch_traces[0]["user_prompt"] if batch_traces else "",
        "user_prompt_chars": batch_traces[0]["user_prompt_chars"] if batch_traces else 0,
        "raw_response": {"goals": [g.model_dump() for g in all_raw_goals]},
    }
    path = OUTPUT_DIR / account_id / "s1_trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(trace, indent=2))
    tmp.replace(path)


def write_goals(stage_out: GoalsStageOutput) -> Path:
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
    goals: list[Goal] = []
    evidence: dict[str, Evidence] = {}
    warnings: list[str] = []
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

        files_with_dates: list[tuple[str, str]] = []
        for ev_id in evidence_ids:
            ev_obj = evidence[ev_id]
            loc = ev_obj.locator
            if isinstance(loc, TranscriptLocator) and loc.date:
                files_with_dates.append((loc.file, loc.date))
        files_with_dates.sort(key=lambda t: t[1])
        seen_files: set[str] = set()
        ordered_files: list[str] = []
        for f, _ in files_with_dates:
            if f not in seen_files:
                seen_files.add(f)
                ordered_files.append(f)
        first_date = files_with_dates[0][1] if files_with_dates else None
        last_date = files_with_dates[-1][1] if files_with_dates else None

        goals.append(Goal(
            id=f"g_{len(goals) + 1:03d}",
            statement=g.statement,
            category=g.category,
            confidence=g.confidence,
            evidence_ids=evidence_ids,
            mentioned_in_files=ordered_files,
            first_mentioned_date=first_date,
            last_mentioned_date=last_date,
        ))

    return GoalsStageOutput(
        account_id=account_id,
        goals=goals,
        evidence=evidence,
        warnings=warnings,
    )
