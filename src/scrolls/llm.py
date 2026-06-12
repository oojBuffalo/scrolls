"""Shared transport for the opt-in LLM tier (ADRs 0015, 0025).

Every LLM engine — classification (`classify_llm`), concept summaries
(`kb_llm`) — makes the same kind of call: one Messages request with a
structured-output schema, credentials from the environment, and the
same auth failure modes. That call lives here once, so each engine
brings only its prompt, schema, and validation.

Engines stay injectable (tests pass a fake completer), and the SDK
import stays lazy: only a command that actually reaches the API pays
for it.
"""

from __future__ import annotations

from typing import Callable

# One model choice for the whole tier: every engine defaults to the same
# model, overridable per invocation by $SCROLLS_LLM_MODEL and per library
# by config.toml's `[classify] llm_model` (ADR 0016).
DEFAULT_MODEL = "claude-opus-4-8"
MODEL_ENV = "SCROLLS_LLM_MODEL"

# A completer takes (system_prompt, user_prompt, model) and returns the
# model's JSON text. Engines bind their schema and token cap when they
# wrap `anthropic_complete` as their default completer.
Completer = Callable[[str, str, str], str]


class LLMError(Exception):
    """The model call or its response could not be used."""


class LLMAuthError(LLMError):
    """No usable Anthropic credentials; retrying other work is pointless."""


def anthropic_complete(
    system: str, user: str, model: str, *, schema: dict, max_tokens: int
) -> str:
    """One Messages API call with structured outputs; returns the JSON text."""
    import anthropic  # lazy: only commands that reach the API pay the import

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
    except TypeError as exc:
        # The SDK raises TypeError when no credentials resolve — at client
        # construction in some versions, while building the request in
        # others. Any other TypeError is a real bug and must surface.
        if "authentication" not in str(exc).lower():
            raise
        raise LLMAuthError(
            "llm engine needs Anthropic credentials: set ANTHROPIC_API_KEY "
            f"({exc})"
        ) from exc
    except anthropic.AuthenticationError as exc:
        raise LLMAuthError(f"Anthropic rejected the credentials: {exc}") from exc
    except anthropic.APIError as exc:
        raise LLMError(f"Anthropic API error: {exc}") from exc

    if response.stop_reason == "refusal":
        raise LLMError("model declined this request")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise LLMError(
            f"model returned no text (stop_reason: {response.stop_reason})"
        )
    return text
