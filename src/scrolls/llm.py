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

import time
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

# A batch completer takes (system_prompt, [(custom_id, user_prompt)...],
# model) and returns each request's raw JSON text — or the LLMError it hit
# — keyed by custom_id. Engines bind their schema and token cap when they
# wrap `anthropic_complete_batch`.
BatchCompleter = Callable[
    [str, "list[tuple[str, str]]", str], "dict[str, str | LLMError]"
]


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


# The Message Batches transport (ADR 0022, ADR 0032): the same structured
# call as `anthropic_complete`, submitted asynchronously at half the
# per-token price. Both LLM engines — classification and concept
# summaries — share it, binding only their schema and token cap.
_POLL_INITIAL_SECONDS = 5.0
_POLL_MAX_SECONDS = 60.0
_sleep = time.sleep  # module-level so tests can observe the poll loop


def anthropic_complete_batch(
    system: str,
    requests: list[tuple[str, str]],
    model: str,
    *,
    schema: dict,
    max_tokens: int,
) -> dict[str, str | LLMError]:
    """One Message Batches submission, polled; per-request text or LLMError.

    Each request carries exactly the params of `anthropic_complete`'s
    call, so the model sees identical prompts and the same structured
    output schema — the Batches API just halves the per-token price.
    Polling blocks until the batch ends (5s doubling to 60s, bounded by
    the API at 24h); Ctrl-C loses only the result mapping, and re-running
    resubmits. Per-request failures (errored, expired, canceled, a
    refusal, an empty response) map to LLMError values keyed by custom_id;
    whole-batch failures raise — LLMAuthError when no credentials resolve,
    LLMError when the submission itself is rejected.
    """
    import anthropic  # lazy: only a --batch command pays the import

    try:
        client = anthropic.Anthropic()
        batch = client.messages.batches.create(
            requests=[
                {
                    "custom_id": custom_id,
                    "params": {
                        "model": model,
                        "max_tokens": max_tokens,
                        "system": system,
                        "output_config": {
                            "format": {"type": "json_schema", "schema": schema}
                        },
                        "messages": [{"role": "user", "content": user}],
                    },
                }
                for custom_id, user in requests
            ]
        )
        delay = _POLL_INITIAL_SECONDS
        while batch.processing_status != "ended":
            _sleep(delay)
            delay = min(delay * 2, _POLL_MAX_SECONDS)
            batch = client.messages.batches.retrieve(batch.id)
        return {
            entry.custom_id: _batch_entry_outcome(entry)
            for entry in client.messages.batches.results(batch.id)
        }
    except TypeError as exc:
        # see anthropic_complete: the SDK's no-credentials TypeError
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


def _batch_entry_outcome(entry) -> str | LLMError:
    """One batch result entry's raw text, or the LLMError for its failure."""
    result = entry.result
    if result.type == "succeeded":
        message = result.message
        if message.stop_reason == "refusal":
            return LLMError("model declined this request")
        text = next((b.text for b in message.content if b.type == "text"), "")
        if not text:
            return LLMError(
                f"model returned no text (stop_reason: {message.stop_reason})"
            )
        return text
    if result.type == "errored":
        return LLMError(f"batch request errored: {result.error}")
    return LLMError(f"batch request {result.type}")  # canceled / expired
