"""config.toml reading (IDEAS.md §8's reserved [classify] section, ADR 0016).

The settings the library actually reads. The `[classify]` table selects the
default engine for `scrolls classify` and the model for the LLM engine. The
`[media]` table bounds what a bulk capture pulls down. Per-invocation
overrides always win — the `--engine` flag beats `default_engine`,
`$SCROLLS_LLM_MODEL` beats `llm_model`, and `--max-bytes` beats `max_bytes`.

Only the CLI loads config (it's a process concern, like JSON encoding
and exit codes); engine modules keep taking explicit parameters.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from scrolls.llm import DEFAULT_MODEL, MODEL_ENV

ENGINES = ("rules", "llm")

# A bulk capture is bounded by default, because the cost is wildly uneven: in
# the first full Wikipedia run 23 of 5,416 files held 4.1 GB of 5.7 GB, and one
# `.webm` alone was 2.5 GB. 25 MB keeps every diagram, photo and short clip.
DEFAULT_MAX_MEDIA_BYTES = 25 * 1024 * 1024

# Rasters wider than this are captured at a thumbnail instead (ADR 0110).
DEFAULT_MAX_IMAGE_WIDTH = 1600

# Per-type caps overriding `max_bytes`. A `pdf` is the one large class that is
# *text*: an agent can read it, so size alone is a bad reason to drop it. `None`
# means no cap for that type.
DEFAULT_MEDIA_TYPE_LIMITS: dict[str, int | None] = {"pdf": None}


class ConfigError(ValueError):
    """config.toml exists but cannot be used as written."""


@dataclass(frozen=True)
class ScrollsConfig:
    default_engine: str = "rules"
    llm_model: str | None = None
    max_media_bytes: int | None = DEFAULT_MAX_MEDIA_BYTES
    max_image_width: int = DEFAULT_MAX_IMAGE_WIDTH
    media_type_limits: Mapping[str, int | None] = field(
        default_factory=lambda: dict(DEFAULT_MEDIA_TYPE_LIMITS)
    )

    def media_limit(self, media_type: str | None) -> int | None:
        """The byte cap for one media type, or None when it is uncapped.

        Args:
            media_type: The ref's `type` (`image`, `video`, `pdf`, …).

        Returns:
            The cap in bytes, or None for no cap.
        """
        if media_type in self.media_type_limits:
            return self.media_type_limits[media_type]
        return self.max_media_bytes


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
    media = data.get("media", {})
    if not isinstance(media, dict):
        raise ConfigError(f"{config_path.name}: [media] must be a table")
    max_bytes = _positive_or_none(config_path, media, "max_bytes", DEFAULT_MAX_MEDIA_BYTES)
    max_width = _positive_or_none(config_path, media, "max_image_width", DEFAULT_MAX_IMAGE_WIDTH)
    if max_width is None:
        raise ConfigError(f"{config_path.name}: [media] max_image_width must be positive")
    limits = dict(DEFAULT_MEDIA_TYPE_LIMITS)
    by_type = media.get("max_bytes_by_type")
    if by_type is not None:
        if not isinstance(by_type, dict):
            raise ConfigError(
                f"{config_path.name}: [media.max_bytes_by_type] must be a table"
            )
        # only what the operator wrote is validated; the built-in defaults are
        # already valid, and `None` there means "this type is uncapped"
        for name in by_type:
            limits[name] = _positive_or_none(
                config_path, by_type, name, None, table="media.max_bytes_by_type"
            )
    return ScrollsConfig(
        default_engine=engine,
        llm_model=llm_model,
        max_media_bytes=max_bytes,
        max_image_width=max_width,
        media_type_limits=limits,
    )


def _positive_or_none(
    config_path: Path,
    values: dict,
    key: str,
    default: int | None,
    *,
    table: str = "media",
) -> int | None:
    """Read a size limit; `0` means "no limit" and reads back as None.

    Args:
        config_path: The file being read, for error messages.
        values: The TOML table holding the key.
        key: The key to read.
        default: The value when the key is absent.
        table: The table's name, for error messages.

    Returns:
        A positive int, or None for no limit.

    Raises:
        ConfigError: The value is not a non-negative integer.
    """
    if key not in values:
        return default
    value = values[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(
            f"{config_path.name}: [{table}] {key} must be a non-negative "
            f"integer (0 for no limit), got {value!r}"
        )
    return value or None


def resolve_llm_model(config: ScrollsConfig) -> str:
    """env > config > default — the per-invocation override always wins."""
    return os.environ.get(MODEL_ENV) or config.llm_model or DEFAULT_MODEL
