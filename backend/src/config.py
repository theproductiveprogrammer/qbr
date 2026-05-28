from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .store import INPUT_DIR

CONFIG_FILENAME = "pipeline.config.json"

# Defaults — used when pipeline.config.json is missing OR a field is unset.
# Sized for gpt-5.4-mini's 128k input context, leaving ~48k headroom for the
# system prompt + structured-output schema overhead.
DEFAULT_MAX_EXTRACTION_TOKENS = 80_000


@dataclass(frozen=True)
class PipelineConfig:
    max_extraction_tokens: int = DEFAULT_MAX_EXTRACTION_TOKENS


@lru_cache(maxsize=1)
def load_pipeline_config() -> PipelineConfig:
    # The problem is: per-account corpora can grow beyond what fits in a single
    # LLM call (10+ long transcripts, future emails). The token budget that
    # triggers multi-batch extraction is a tuning knob — someone should be able
    # to lower it for testing or raise it as the model context grows.
    # The way we solve this is: optional config file at data/input/, with cached
    # load + sane defaults. Edit + restart to apply.
    # flow: stages/s1_goals.py extract_goals() -> load_pipeline_config() <-- HERE
    path = INPUT_DIR / CONFIG_FILENAME
    if not path.exists():
        return PipelineConfig()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return PipelineConfig()
    return PipelineConfig(
        max_extraction_tokens=int(data.get("max_extraction_tokens", DEFAULT_MAX_EXTRACTION_TOKENS)),
    )
