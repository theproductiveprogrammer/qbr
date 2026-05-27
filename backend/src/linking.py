from __future__ import annotations

from typing import Any

from .schemas import EmailLocator, TranscriptLocator


def normalize(s: str) -> str:
    # The problem is: LLM-emitted quotes routinely differ from source by whitespace,
    # case, or trailing punctuation while being faithful in spirit.
    # The way we solve this is: lowercase + collapse runs of whitespace before matching.
    return " ".join(s.lower().split())


def link_quote(
    quote: str,
    file: str,
    corpus: dict[str, Any],
) -> TranscriptLocator | EmailLocator | None:
    # The problem is: LLMs hallucinate or paraphrase quotes, and forcing them to emit
    # precise line numbers eats tokens for something the pipeline can derive
    # deterministically. The linker must support both call transcripts and email
    # threads — same logic, different parsed shape.
    # The way we solve this is: walk transcripts then emails for a file whose name
    # matches, substring-match the normalized quote against parsed turns/messages,
    # return the matching locator (carrying line range + per-type metadata). No
    # match → None, and the caller drops the evidence as hallucinated.
    # flow: stages/*.py -> link_quote() <-- HERE -> Evidence with verified locator
    needle = normalize(quote)
    if not needle:
        return None

    transcript = next(
        (t for t in corpus.get("transcripts", []) if t["file"] == file),
        None,
    )
    if transcript is not None:
        for turn in transcript["turns"]:
            if needle in normalize(turn["text"]):
                return TranscriptLocator(
                    kind="transcript",
                    file=file,
                    line_start=turn["line_start"],
                    line_end=turn["line_end"],
                    timestamp=turn["timestamp"],
                    date=transcript.get("recorded_date"),
                )
        return None

    email = next(
        (e for e in corpus.get("emails", []) if e["file"] == file),
        None,
    )
    if email is not None:
        for msg in email["messages"]:
            if needle in normalize(msg["body"]):
                return EmailLocator(
                    kind="email",
                    file=file,
                    line_start=msg["line_start"],
                    line_end=msg["line_end"],
                    date=msg["date"],
                    sender=msg["sender"],
                )
        return None

    return None
