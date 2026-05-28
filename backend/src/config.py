from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .store import DATA_DIR

CONFIG_FILENAME = "pipeline.config.json"

# Defaults — used when pipeline.config.json is missing OR a field is unset.
# Sized for gpt-5.4-mini's 128k input context, leaving ~48k headroom for the
# system prompt + structured-output schema overhead.
DEFAULT_MAX_EXTRACTION_TOKENS = 80_000


DEFAULT_EXTRACTION_TEMPERATURE = 0.3
DEFAULT_EXTRACTION_SEED: int | None = None
DEFAULT_EXTRACTION_MODEL = "gpt-5.5"
# Final cap on goals surfaced per brief AFTER cross-batch dedup. Mirrored into
# the goal_extract prompt at runtime so the LLM's stated upper bound matches.
# Most accounts have 2-3 real strategic goals; 4 leaves room for one bonus.
DEFAULT_TOP_GOALS = 4


@dataclass(frozen=True)
class PipelineConfig:
    max_extraction_tokens: int = DEFAULT_MAX_EXTRACTION_TOKENS
    # 0.0 = greedy/reproducible. 0.2-0.5 = delivery default: mostly stable with
    # enough variance to occasionally surface a different framing on re-run.
    extraction_temperature: float = DEFAULT_EXTRACTION_TEMPERATURE
    # Pin to an int for near-deterministic runs (OpenAI best-effort). None = no seed.
    extraction_seed: int | None = DEFAULT_EXTRACTION_SEED
    # Model id used by stage 1 goal extraction. gpt-5.5 = stronger verbatim
    # discipline + better instruction-following; gpt-5.4-mini = cheaper, more
    # variable. Other LLM stages (when they land) have their own config knobs.
    extraction_model: str = DEFAULT_EXTRACTION_MODEL
    # Final goal cap surfaced per brief. Threaded into both the prompt (hard
    # cap the LLM is told to respect) AND the post-dedup truncation, so
    # changing this one number stays consistent end-to-end.
    top_goals: int = DEFAULT_TOP_GOALS


@lru_cache(maxsize=1)
def load_pipeline_config() -> PipelineConfig:
    # The problem is: extraction behavior has knobs the operator may want to
    # tune — token budget (scales with model context), temperature (controls
    # run-to-run variance), seed (reproducibility for demos / regression tests).
    # The way we solve this is: optional config file at data/input/, cached
    # singleton load, sane delivery defaults. Edit + restart to apply.
    # flow: stages/s1_goals.py extract_goals() -> load_pipeline_config() <-- HERE
    path = DATA_DIR / CONFIG_FILENAME
    if not path.exists():
        return PipelineConfig()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return PipelineConfig()
    seed_val = data.get("extraction_seed", DEFAULT_EXTRACTION_SEED)
    return PipelineConfig(
        max_extraction_tokens=int(data.get("max_extraction_tokens", DEFAULT_MAX_EXTRACTION_TOKENS)),
        extraction_temperature=float(data.get("extraction_temperature", DEFAULT_EXTRACTION_TEMPERATURE)),
        extraction_seed=int(seed_val) if seed_val is not None else None,
        extraction_model=str(data.get("extraction_model", DEFAULT_EXTRACTION_MODEL)),
        top_goals=max(1, int(data.get("top_goals", DEFAULT_TOP_GOALS))),
    )
