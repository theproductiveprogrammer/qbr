from __future__ import annotations

import os
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel

# Newer reasoning-style models (gpt-5.5, o-series) reject custom temperature /
# seed — they only support their built-in defaults. Detect by name prefix so we
# pass-through cleanly instead of crashing on first call.
_NO_SAMPLING_PARAMS_PREFIXES = ("gpt-5.5", "gpt-5.6", "o1", "o3", "o4")


def _supports_sampling_params(model: str) -> bool:
    return not any(model.startswith(p) for p in _NO_SAMPLING_PARAMS_PREFIXES)

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
    temperature: float | None = None,
    seed: int | None = None,
) -> T:
    # The problem is: every LLM call in this pipeline must produce structured output
    # conforming to a pydantic schema, AND callers want optional control over
    # sampling (temperature for run-to-run variance, seed for reproducibility).
    # The way we solve this is: thin wrapper around OpenAI's structured-outputs
    # parse() that conditionally forwards temperature + seed (None = SDK defaults),
    # and surfaces refusals as exceptions instead of silently returning None.
    # flow: stages/* -> parse_structured() <-- HERE -> OpenAI API
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": response_format,
    }
    if _supports_sampling_params(model):
        if temperature is not None:
            kwargs["temperature"] = temperature
        if seed is not None:
            kwargs["seed"] = seed

    response = _get_client().beta.chat.completions.parse(**kwargs)
    msg = response.choices[0].message
    if msg.refusal:
        raise RuntimeError(f"OpenAI refused the request: {msg.refusal}")
    if msg.parsed is None:
        raise RuntimeError("OpenAI returned no parsed content and no refusal — unexpected.")
    return msg.parsed
