from __future__ import annotations

import pytest

from src.ingest import ACCOUNTS, build_corpus, parse_transcript
from src.store import INPUT_DIR


@pytest.mark.parametrize("account_id", list(ACCOUNTS.keys()))
def test_build_corpus_finds_transcripts(account_id: str) -> None:
    # The problem is: silent zero-transcripts ingest would let downstream stages run
    # on empty input and produce vacuous goals.
    # The way we solve this is: assert each account ingests with at least one parsed
    # transcript and at least one turn per transcript.
    corpus = build_corpus(account_id)
    assert corpus["account_id"] == account_id
    assert corpus["account_name"]
    assert corpus["transcripts"], f"no transcripts matched for {account_id}"
    for t in corpus["transcripts"]:
        assert t["turns"], f"no turns parsed in {t['file']}"


def test_transcript_turns_have_required_fields() -> None:
    # The problem is: stage 1 cites evidence by (file, line_start, line_end, timestamp);
    # a parser that drops one of those fields would render evidence un-verifiable.
    # The way we solve this is: pick one known-rich transcript and inspect the first
    # few turns for the four locator fields plus text.
    sample = next(INPUT_DIR.glob("call-transcript--meridian-furniture-account-review.txt"), None)
    assert sample is not None, "Meridian account-review transcript is missing from data/input"
    turns = parse_transcript(sample)
    assert len(turns) > 10, "expected a healthy account-review transcript"
    for t in turns[:5]:
        assert t.line_start > 0
        assert t.line_end >= t.line_start
        assert ":" in t.timestamp  # MM:SS-ish
        assert t.speaker
        assert t.text


def test_meridian_usage_row_loads() -> None:
    # The problem is: the xlsx → usage-row mapping depends on string equality with
    # the canonical org name; a typo or rename would silently return None.
    # The way we solve this is: assert Meridian's usage row loads with key columns
    # we know are present (Auscraft Furniture).
    corpus = build_corpus("meridian")
    usage = corpus["usage"]
    assert usage is not None
    assert "RECEIVED MESSAGES LAST 30DAYS" in usage
    assert "REVIEW INVITES LAST 30DAYS" in usage


def test_apex_has_no_usage_row() -> None:
    corpus = build_corpus("apex")
    assert corpus["usage"] is None
