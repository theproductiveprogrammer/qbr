from __future__ import annotations

from src.stages.s1_goals import (
    _ExtractedEvidence,
    _ExtractedGoal,
    _batch_transcripts,
    _cap_goals,
    _dedupe_goals,
    _estimate_transcript_tokens,
)


def _mk_transcript(file: str, text_chars: int) -> dict:
    # A transcript with one giant turn whose text takes the requested char count.
    return {
        "file": file,
        "n_lines": 100,
        "recorded_date": "2026-01-01",
        "turns": [{
            "line_start": 1,
            "line_end": 10,
            "timestamp": "0:00",
            "speaker": "Customer",
            "text": "x" * text_chars,
        }],
    }


def test_batch_single_transcript_fits_in_one_batch() -> None:
    transcripts = [_mk_transcript("a.txt", 10_000)]
    batches = _batch_transcripts(transcripts, max_tokens=80_000)
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_batch_packs_multiple_until_budget_exceeds() -> None:
    # The problem is: greedy batching should pack as many transcripts as fit and
    # only split when adding the next one would exceed the budget.
    # Each "big" transcript is ~12000 chars ≈ 3200 tokens; budget = 5000 forces
    # one transcript per batch (because 2 would exceed).
    transcripts = [_mk_transcript(f"t{i}.txt", 12_000) for i in range(10)]
    batches = _batch_transcripts(transcripts, max_tokens=5000)
    assert len(batches) == 10  # each one fills its own batch
    # Bigger budget = fewer batches
    batches_big = _batch_transcripts(transcripts, max_tokens=80_000)
    assert len(batches_big) == 1


def test_batch_chronological_order_preserved() -> None:
    transcripts = [_mk_transcript(f"t{i}.txt", 1000) for i in range(5)]
    batches = _batch_transcripts(transcripts, max_tokens=3000)
    # Flatten and assert files appear in the same order they were fed
    flat_files = [t["file"] for batch in batches for t in batch]
    assert flat_files == ["t0.txt", "t1.txt", "t2.txt", "t3.txt", "t4.txt"]


def test_batch_single_transcript_exceeding_budget_still_gets_emitted() -> None:
    # The problem is: a single huge transcript that exceeds the budget alone
    # would otherwise be silently dropped.
    # The way we solve this is: always pack at least one transcript per batch.
    transcripts = [_mk_transcript("huge.txt", 1_000_000)]  # way over any budget
    batches = _batch_transcripts(transcripts, max_tokens=1000)
    assert len(batches) == 1
    assert batches[0][0]["file"] == "huge.txt"


def test_estimate_transcript_tokens_scales_with_content() -> None:
    small = _mk_transcript("a.txt", 100)
    big = _mk_transcript("b.txt", 10_000)
    assert _estimate_transcript_tokens(big) > _estimate_transcript_tokens(small) * 10


def _mk_goal(statement: str, category: str = "reviews", confidence: str = "high", evidence_count: int = 1) -> _ExtractedGoal:
    return _ExtractedGoal(
        statement=statement,
        category=category,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        evidence=[
            _ExtractedEvidence(file=f"t{i}.txt", quote=f"quote {i}")
            for i in range(evidence_count)
        ],
    )


def test_dedupe_merges_all_goals_in_same_category() -> None:
    # The problem is: per-batch extraction can emit multiple goals in the same
    # category — sometimes the same goal rephrased, sometimes related-but-distinct.
    # The way we solve this is: dedupe by category. Categories are the controlled
    # vocabulary that maps to features; two goals in the same category surface
    # the same downstream recommendations. One canonical goal per category.
    goals = [
        _mk_goal("Increase Google review velocity to improve Map Pack ranking"),
        _mk_goal("Increase Google reviews to boost visibility"),
        _mk_goal("Reply to reviews faster"),  # all reviews — collapse to one
    ]
    merged = _dedupe_goals(goals)
    assert len(merged) == 1
    # Longest statement wins
    assert merged[0].statement == "Increase Google review velocity to improve Map Pack ranking"


def test_dedupe_combines_evidence_across_merged_goals() -> None:
    goals = [
        _mk_goal("Goal A", evidence_count=2),  # files t0, t1
        _mk_goal("Goal A longer phrasing", evidence_count=2),  # also t0, t1 (same)
        _mk_goal("Goal A again", evidence_count=3),  # t0, t1, t2
    ]
    merged = _dedupe_goals(goals)
    assert len(merged) == 1
    # Unique evidence by (file, quote-prefix) — t0, t1, t2 = 3 distinct
    assert len(merged[0].evidence) == 3


def test_dedupe_keeps_goals_in_different_categories() -> None:
    goals = [
        _mk_goal("Get more reviews", category="reviews"),
        _mk_goal("Get more reviews from leads", category="lead_response"),
    ]
    merged = _dedupe_goals(goals)
    assert len(merged) == 2  # different categories → never merge


def test_dedupe_takes_max_confidence_from_cluster() -> None:
    goals = [
        _mk_goal("Goal", confidence="low"),
        _mk_goal("Goal", confidence="high"),
        _mk_goal("Goal", confidence="med"),
    ]
    merged = _dedupe_goals(goals)
    assert len(merged) == 1
    assert merged[0].confidence == "high"


def test_cap_goals_returns_top_k_by_confidence_then_evidence() -> None:
    goals = [
        _mk_goal("low confidence goal", confidence="low", evidence_count=1),
        _mk_goal("high confidence goal", confidence="high", evidence_count=1),
        _mk_goal("med confidence goal", confidence="med", evidence_count=3),
        _mk_goal("high w/ more evidence", confidence="high", evidence_count=5),
        _mk_goal("low w/ lots of evidence", confidence="low", evidence_count=20),
    ]
    capped = _cap_goals(goals, cap=3)
    # high+5ev should win, then high+1ev, then med+3ev (3*10+3=33 > 1*10+20=30)
    assert len(capped) == 3
    statements = [g.statement for g in capped]
    assert "high w/ more evidence" in statements
    assert "high confidence goal" in statements
