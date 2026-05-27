from __future__ import annotations

import os
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

# Model defaults per DESIGN.md §7. Configurable at call site if a stage needs different.
MODEL_EXTRACTION = "gpt-5.4-mini"
MODEL_NARRATIVE = "gpt-5.5"

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    # The problem is: every stage that calls OpenAI needs a configured client, and
    # missing API keys should fail with a clear message rather than a stack trace from
    # the SDK's first request.
    # The way we solve this is: lazy singleton with an explicit key check on first use.
    # flow: any stage -> parse_structured() -> _get_client() <-- HERE
    global _client
    if _client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env at the repo root "
                "(`echo OPENAI_API_KEY=sk-... > .env`) or export it in your shell."
            )
        _client = OpenAI()
    return _client


def parse_structured(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    response_format: type[T],
) -> T:
    # The problem is: every LLM call in this pipeline must produce structured output
    # conforming to a pydantic schema so downstream code can rely on its shape.
    # The way we solve this is: thin wrapper around OpenAI's structured-outputs
    # parse() that surfaces refusals as exceptions instead of silently returning None.
    # flow: stages/* -> parse_structured() <-- HERE -> OpenAI API
    response = _get_client().beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=response_format,
    )
    msg = response.choices[0].message
    if msg.refusal:
        raise RuntimeError(f"OpenAI refused the request: {msg.refusal}")
    if msg.parsed is None:
        raise RuntimeError("OpenAI returned no parsed content and no refusal — unexpected.")
    return msg.parsed
