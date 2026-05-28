from __future__ import annotations

from typing import Any

from .schemas import EmailLocator, TranscriptLocator


_ELLIPSIS_MARKERS = ("…", "...", "[...]")
_FRAGMENT_SENTINEL = "|@FRAG@|"


def normalize(s: str) -> str:
    # The problem is: LLM-emitted quotes routinely differ from source by whitespace,
    # case, or trailing punctuation while being faithful in spirit.
    # The way we solve this is: lowercase + collapse runs of whitespace before matching.
    return " ".join(s.lower().split())


def _split_fragments(quote: str) -> list[str]:
    # The problem is: LLMs love adding ellipses to mark elided text mid-quote
    # ("I want... more reviews"), but our line-anchored matcher needs to verify each
    # piece appears in order within the same source turn.
    # The way we solve this is: replace any ellipsis marker with a visible sentinel,
    # split on it, normalize each piece, drop empties. A single fragment means no
    # ellipsis was used and the caller falls through to direct substring.
    text = quote
    for marker in _ELLIPSIS_MARKERS:
        text = text.replace(marker, _FRAGMENT_SENTINEL)
    return [normalize(p) for p in text.split(_FRAGMENT_SENTINEL) if normalize(p)]


def _fragments_in_order(fragments: list[str], hay: str) -> bool:
    # All fragments must appear in `hay` in the order given. Used as a fallback
    # when the LLM elided text with ellipsis.
    pos = 0
    for frag in fragments:
        idx = hay.find(frag, pos)
        if idx == -1:
            return False
        pos = idx + len(frag)
    return True


def link_quote(
    quote: str,
    file: str,
    corpus: dict[str, Any],
) -> TranscriptLocator | EmailLocator | None:
    # The problem is: LLMs hallucinate or paraphrase quotes, AND confuse similarly-
    # named files (e.g. attributing a quote to `account-review.txt` when it actually
    # lives in `account-review-session-b.txt`). The linker must support both kinds
    # of recovery without opening the door to false-positives.
    # The way we solve this is: three passes. (1) Direct substring in the named
    # file. (2) Ellipsis-fragment-order match in the named file. (3) Cross-file
    # fallback — search all transcripts/emails; accept only if exactly ONE other
    # file matches (ambiguous → drop).
    # flow: stages/*.py -> link_quote() <-- HERE -> Evidence with verified locator
    needle = normalize(quote)
    if not needle:
        return None
    fragments = _split_fragments(quote)
    has_ellipsis = len(fragments) > 1

    # Pass 1+2: try the file the LLM named.
    direct = _try_match(needle, fragments, has_ellipsis, file, corpus)
    if direct is not None:
        return direct

    # Pass 3: cross-file fallback for misattributed quotes.
    matches: list[TranscriptLocator | EmailLocator] = []
    for t in corpus.get("transcripts", []):
        if t["file"] == file:
            continue
        m = _try_match(needle, fragments, has_ellipsis, t["file"], corpus)
        if m is not None:
            matches.append(m)
    for e in corpus.get("emails", []):
        if e["file"] == file:
            continue
        m = _try_match(needle, fragments, has_ellipsis, e["file"], corpus)
        if m is not None:
            matches.append(m)

    if len(matches) == 1:
        return matches[0]
    return None


def _try_match(
    needle: str,
    fragments: list[str],
    has_ellipsis: bool,
    file: str,
    corpus: dict[str, Any],
) -> TranscriptLocator | EmailLocator | None:
    transcript = next(
        (t for t in corpus.get("transcripts", []) if t["file"] == file),
        None,
    )
    if transcript is not None:
        for turn in transcript["turns"]:
            hay = normalize(turn["text"])
            if needle in hay or (has_ellipsis and _fragments_in_order(fragments, hay)):
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
            hay = normalize(msg["body"])
            if needle in hay or (has_ellipsis and _fragments_in_order(fragments, hay)):
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
