from __future__ import annotations

from src.ingest import build_corpus
from src.linking import link_quote, normalize


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize("  Hello   WORLD  ") == "hello world"
    assert normalize("a\nb\tc") == "a b c"


def test_link_exact_quote_returns_locator() -> None:
    # The problem is: the LLM may quote a customer line verbatim — the linker must
    # find it and attach the correct line range + timestamp from the parsed corpus.
    # The way we solve this is: pull a known customer line from Meridian, hand it to
    # the linker, assert the locator points back to that turn.
    corpus = build_corpus("meridian")
    file = "call-transcript--meridian-furniture-account-review.txt"
    quote = "We sent them always like SMS, but they don't make the, I mean, review on the first SMS"

    loc = link_quote(quote, file, corpus)
    assert loc is not None
    assert loc.file == file
    assert loc.line_start == 543  # known from prior grounding
    assert loc.line_end == 544
    assert loc.timestamp == "30:57"


def test_link_whitespace_variant_still_matches() -> None:
    # LLMs frequently normalize whitespace differently than the source. The linker
    # must tolerate that without losing the citation.
    corpus = build_corpus("meridian")
    file = "call-transcript--meridian-furniture-account-review.txt"
    quote = "We  sent  them   always   like   SMS,   but  they  don't  make  the,  I  mean,  review  on  the  first  SMS"

    loc = link_quote(quote, file, corpus)
    assert loc is not None
    assert loc.line_start == 543


def test_link_hallucinated_quote_returns_none() -> None:
    # The problem is: hallucinated quotes must not silently slip through with fake
    # locators attached.
    # The way we solve this is: a quote that doesn't appear in the source returns
    # None, and the caller drops the evidence.
    corpus = build_corpus("meridian")
    file = "call-transcript--meridian-furniture-account-review.txt"
    quote = "Our quarterly OKR is to launch the AI-powered retention engine by Q3"

    assert link_quote(quote, file, corpus) is None


def test_link_unknown_file_with_unique_quote_recovers_via_cross_file_fallback() -> None:
    # The problem is: the LLM often confuses similarly-named files (e.g. names a
    # quote as being in `account-review.txt` when it actually lives in
    # `account-review-session-b.txt`).
    # The way we solve this is: when the named file doesn't match, search all
    # other transcripts; if exactly ONE contains the quote, use it.
    corpus = build_corpus("meridian")
    # This quote exists in exactly one Meridian transcript — cross-file fallback
    # should recover it even when the named file is wrong.
    quote = "We sent them always like SMS"
    loc = link_quote(quote, "call-transcript--does-not-exist.txt", corpus)
    assert loc is not None
    assert loc.kind == "transcript"
    assert "account-review" in loc.file


def test_link_unknown_file_with_nonexistent_quote_returns_none() -> None:
    corpus = build_corpus("meridian")
    quote = "Our quarterly OKR is to launch the AI-powered retention engine by Q3"
    assert link_quote(quote, "call-transcript--does-not-exist.txt", corpus) is None


def test_link_email_quote_returns_email_locator() -> None:
    # The problem is: when email data lands, the linker must find the quote inside an
    # email body and return an EmailLocator (not a TranscriptLocator), carrying date
    # and sender for the AM-facing evidence rail.
    # The way we solve this is: synthetic in-memory corpus with one email thread,
    # assert the returned locator is kind="email" with the right fields.
    corpus = {
        "account_id": "test",
        "transcripts": [],
        "emails": [{
            "file": "email-thread--q1-priorities.eml",
            "messages": [
                {
                    "line_start": 5,
                    "line_end": 12,
                    "date": "2026-01-15",
                    "sender": "matt@meridian.example",
                    "subject": "Re: Q1 priorities",
                    "body": (
                        "Hi, following up on our call. To recap: we really want to "
                        "grow our Google review count this quarter and beat the "
                        "Map Pack competition."
                    ),
                },
            ],
        }],
        "usage": None,
    }
    loc = link_quote(
        "we really want to grow our Google review count",
        "email-thread--q1-priorities.eml",
        corpus,
    )
    assert loc is not None
    assert loc.kind == "email"
    assert loc.line_start == 5
    assert loc.line_end == 12
    assert loc.date == "2026-01-15"
    assert loc.sender == "matt@meridian.example"


def test_link_quote_with_ellipsis_matches_fragments_in_order() -> None:
    # The problem is: the LLM often emits a quote like "foo... bar" to indicate
    # elided text mid-quote, even when told not to. The linker should match this
    # to a single source turn that contains "foo [some words] bar".
    # The way we solve this is: ellipsis-aware fallback that splits on the marker
    # and checks each fragment appears in the same turn in the original order.
    corpus = {
        "transcripts": [{
            "file": "test.txt",
            "recorded_date": "2026-01-01",
            "turns": [{
                "line_start": 10,
                "line_end": 12,
                "timestamp": "1:23",
                "speaker": "Customer",
                "text": "I really want to grow our Google review count to push the map pack ranking up this quarter",
            }],
        }],
    }
    quote_with_ellipsis = "I really want to grow our Google review count to push the map pack"
    loc = link_quote(quote_with_ellipsis, "test.txt", corpus)
    assert loc is not None
    assert loc.line_start == 10

    # Now with an actual ellipsis in the middle
    elided = "I really want to grow our Google review count… push the map pack"
    loc2 = link_quote(elided, "test.txt", corpus)
    assert loc2 is not None
    assert loc2.line_start == 10


def test_link_quote_ellipsis_requires_fragments_in_order() -> None:
    # The problem is: ellipsis matching shouldn't allow fragments to appear in
    # reverse order (that would be unfaithful to the source).
    # The way we solve this is: _fragments_in_order advances `pos` past each
    # match so subsequent fragments must come after.
    corpus = {
        "transcripts": [{
            "file": "test.txt",
            "recorded_date": "2026-01-01",
            "turns": [{
                "line_start": 1,
                "line_end": 1,
                "timestamp": "0:00",
                "speaker": "Customer",
                "text": "We want bar before foo in this order",
            }],
        }],
    }
    # Quote tries to claim foo comes before bar — should NOT match
    quote_reversed = "foo… bar"
    assert link_quote(quote_reversed, "test.txt", corpus) is None


def test_link_hallucinated_email_quote_returns_none() -> None:
    corpus = {
        "transcripts": [],
        "emails": [{
            "file": "email-thread--q1-priorities.eml",
            "messages": [{
                "line_start": 1,
                "line_end": 2,
                "date": "2026-01-15",
                "sender": "matt@example.com",
                "subject": "Hi",
                "body": "Short body.",
            }],
        }],
    }
    assert link_quote("Nope not in here at all", "email-thread--q1-priorities.eml", corpus) is None
