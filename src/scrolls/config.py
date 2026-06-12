"""config.toml reading (IDEAS.md §8's reserved [classify] section, ADR 0016).

The first settings the library actually reads. Scope is deliberately
narrow: the `[classify]` table selects the default engine for
`scrolls classify` and the model for the LLM engine. Per-invocation
overrides always win — the `--engine` flag beats `default_engine`, and
`$SCROLLS_LLM_MODEL` beats `llm_model`.

Only the CLI loads config (it's a process concern, like JSON encoding
and exit codes); engine modules keep taking explicit parameters.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from scrolls.classify_llm import DEFAULT_MODEL, MODEL_ENV

ENGINES = ("rules", "llm")


class ConfigError(ValueError):
    """config.toml exists but cannot be used as written."""


@dataclass(frozen=True)
class ScrollsConfig:
    default_engine: str = "rules"
    llm_model: str | None = None


def load_config(config_path: Path) -> ScrollsConfig:
    """Read config.toml; a missing file is simply the defaults.

    Raises ConfigError for unparseable TOML or invalid values — a
    config the user wrote deserves an honest error, not silent defaults.
    """
    if not config_path.exists():
        return ScrollsConfig()
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path.name}: invalid TOML: {exc}") from exc

    classify = data.get("classify", {})
    if not isinstance(classify, dict):
        raise ConfigError(f"{config_path.name}: [classify] must be a table")
    engine = classify.get("default_engine", "rules")
    if engine not in ENGINES:
        raise ConfigError(
            f"{config_path.name}: [classify] default_engine must be one of "
            f"{'/'.join(ENGINES)}, got {engine!r}"
        )
    llm_model = classify.get("llm_model")
    if llm_model is not None and not isinstance(llm_model, str):
        raise ConfigError(
            f"{config_path.name}: [classify] llm_model must be a string, "
            f"got {llm_model!r}"
        )
    return ScrollsConfig(default_engine=engine, llm_model=llm_model)


def resolve_llm_model(config: ScrollsConfig) -> str:
    """env > config > default — the per-invocation override always wins."""
    return os.environ.get(MODEL_ENV) or config.llm_model or DEFAULT_MODEL
