"""Hugging Face Hub fetch adapter (IDEAS.md §6, ADR 0041).

A saved Hugging Face model or dataset page becomes a clean scroll instead
of a `trafilatura` scrape of its JS-rendered HTML. One GET against the
keyless Hub API (`huggingface.co/api/models|datasets/<id>`) returns the
repo's metadata document, and a second fetches the card
(`<repo>/raw/main/README.md`) — no auth, no runtime dependency.

This is the ML sibling of the package-registry adapters (PyPI, npm, …):
the same JSON-metadata shape, the same author-declared keywords→concepts
mapping. Two facts distinguish it, both confirmed against the live API:

1. **One adapter, two repo kinds.** Models and datasets live on one host
   under different API endpoints, so the repo *kind* rides in the source
   id (`model:<org>/<name>` / `dataset:<org>/<name>`) the way the Stack
   Exchange site does (ADR 0033) — `detect_source` picks the kind off the
   URL, and this adapter routes to `/api/models` or `/api/datasets`
   accordingly. A model classifies as `tool` (an artifact you use, like a
   package), a dataset as `dataset` — literally in the IDEAS.md §8
   vocabulary (ADR 0004).

2. **The Hub flattens everything into one `tags` array.** A repo's tags
   mix author intent (`exbert`) with auto-derived noise (frameworks
   `pytorch`/`jax`, `region:us`, file formats, `endpoints_compatible`).
   Rather than mine that soup, concepts/tags come from the *structured*
   fields — `pipeline_tag`/`task_categories` (the task) and `cardData.tags`
   feed the concept graph (the github-topics parallel, ADR 0007);
   `library_name` and the `license` fill the `tags` facet slot. The flat
   array is read only for its cross-reference prefixes: an `arxiv:<id>`
   tag becomes an `arxiv.org/abs/<id>` link that `scrolls related`
   resolves to the saved arXiv paper (the model↔paper edge, kin to
   ADR 0038's preprint↔published edge), and a `dataset:<name>` tag becomes
   the dataset's Hub page (the model↔dataset edge).

The card README — its YAML frontmatter (where `cardData` comes from)
stripped — is the searchable `extracted_text`; its lead paragraph is the
`summary` (a dataset's `description` field, whitespace-collapsed, is the
fallback when there is no card). A repo with no README, or a failed card
fetch, degrades to a metadata-only scroll (ADR 0002). A curated metadata
subset is kept in `raw_text` for rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://huggingface.co/api"
SITE_ROOT = "https://huggingface.co"

# The metadata fields worth keeping in the index; the response also carries
# large, useless-to-search structures (siblings, config, safetensors,
# widgetData, transformersInfo, spaces) that are dropped (crates curates
# raw_text the same way, ADR 0036).
_RAW_KEYS = (
    "id", "author", "sha", "pipeline_tag", "library_name", "tags",
    "downloads", "likes", "private", "gated", "createdAt", "lastModified",
    "cardData", "description",
)

# A lead-paragraph candidate must be prose, not a heading, badge, image,
# table, blockquote, list, rule, or code fence.
_SKIP_LEAD_PREFIXES = ("#", "<", "|", "![", "[!", ">", "-", "*", "=", "```")

GetJson = Callable[[str], Any]
GetText = Callable[[str], str]


def fetch_item(
    item: ScrollItem,
    *,
    get_json: GetJson | None = None,
    get_text: GetText | None = None,
) -> ScrollItem:
    """Fetch a detected Hub repo's metadata + card; return it at stage 'fetched'.

    Raises FetchError when the source id names no model/dataset repo, the
    request fails, or the Hub has no such repo. The input item is never
    mutated.
    """
    get_json = get_json or _get_json
    get_text = get_text or _get_text
    kind, repo_id = _parse_source_id(item)

    endpoint = "datasets" if kind == "dataset" else "models"
    url = f"{API_ROOT}/{endpoint}/{repo_id}"
    try:
        data = get_json(url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"Hugging Face API request failed: {exc}") from exc

    canonical_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(canonical_id, str) or not canonical_id:
        raise FetchError(f"{kind} not found: {repo_id}")

    card_data = data.get("cardData") if isinstance(data.get("cardData"), dict) else {}
    card = _fetch_card(kind, canonical_id, get_text)
    summary = _summary(kind, data, card)
    tags_list = data.get("tags") if isinstance(data.get("tags"), list) else []

    raw = json.dumps({k: data[k] for k in _RAW_KEYS if k in data}, ensure_ascii=False)
    hashed = card or summary or raw
    method = "huggingface-api:json+card" if card else "huggingface-api:json"
    return replace(
        item,
        title=_title(kind, canonical_id, card_data),
        author=_clean(data.get("author")),
        published_at=_created_date(data) or item.published_at,
        canonical_url=_canonical_url(kind, canonical_id),
        raw_text=raw,
        extracted_text=card,
        summary=summary,
        tags=_tags(kind, data, card_data),
        concepts=_concepts(kind, data, card_data),
        links=_links(tags_list),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "huggingface",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _parse_source_id(item: ScrollItem) -> tuple[str, str]:
    """`(kind, repo_id)` from a `model:<id>`/`dataset:<id>` source id.

    Raises FetchError for a missing id, an unknown kind (`spaces` has no
    adapter), or an empty repo — the cases `detect_source` leaves as the
    source with no fetchable item.
    """
    kind, sep, repo_id = (item.source_id or "").partition(":")
    if not sep or kind not in ("model", "dataset") or not repo_id.strip():
        raise FetchError(f"cannot determine huggingface repo for item {item.id!r}")
    return kind, repo_id.strip()


def _fetch_card(kind: str, repo_id: str, get_text: GetText) -> str | None:
    """The repo's card README, frontmatter stripped, or None on any failure.

    The card is the rich searchable content (the model/dataset card). A
    repo without one — or a transient fetch failure — degrades to a
    metadata-only scroll rather than aborting the fetch (ADR 0002).
    """
    prefix = "datasets/" if kind == "dataset" else ""
    url = f"{SITE_ROOT}/{prefix}{repo_id}/raw/main/README.md"
    try:
        text = get_text(url)
    except (OSError, ValueError):
        return None
    return _strip_frontmatter(text)


def _strip_frontmatter(text: str) -> str | None:
    """Drop a leading `---`-delimited YAML block; return the cleaned body.

    Hub cards open with the YAML frontmatter that becomes `cardData`, so
    the searchable text is everything after it. A document with no
    frontmatter (or an unterminated one) is kept whole.
    """
    body = (text or "").lstrip("\ufeff")  # tolerate a leading UTF-8 BOM
    lines = body.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body = "\n".join(lines[i + 1:])
                break
    return _clean(body)


def _created_date(data: dict[str, Any]) -> str | None:
    """The repo's `createdAt` as UTC ISO 8601, or None.

    `createdAt` is the repo's publication moment (preferred over the
    noisier `lastModified`). Guarded with `isinstance` because
    `to_utc_iso` strips its argument: a malformed non-string value in the
    untrusted response becomes None rather than raising — the sibling
    registry adapters' guard (ADR 0040).
    """
    created = data.get("createdAt")
    return to_utc_iso(created) if isinstance(created, str) else None


def _summary(kind: str, data: dict[str, Any], card: str | None) -> str | None:
    """The card's lead paragraph, else a dataset's `description`, else None.

    The card's first prose paragraph is the cleanest one-line summary, so
    it wins for both kinds. A dataset's `description` field is the fallback
    when no card paragraph is found — but the Hub derives that field crudely
    from the card (heading fragments and tabs included), so its whitespace
    is collapsed. Models have no `description`, so a card-less model is
    honestly summary-less (the metadata still maps).
    """
    lead = _lead_paragraph(card)
    if lead:
        return lead
    if kind == "dataset":
        return _collapse_whitespace(_clean(data.get("description")))
    return None


def _collapse_whitespace(text: str | None) -> str | None:
    """Runs of whitespace (tabs, newlines) collapsed to single spaces, or None."""
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def _lead_paragraph(card: str | None) -> str | None:
    """The first prose paragraph of a card, as one line, or None.

    Headings (ATX `#` and setext `Title\n====`), badges, images, tables,
    blockquotes, lists, rules, and code fences are skipped; the first real
    paragraph's soft-wrapped lines are joined with spaces.
    """
    if not card:
        return None
    for block in re.split(r"\n[ \t]*\n", card):
        block = block.strip()
        if not block or block.startswith(_SKIP_LEAD_PREFIXES):
            continue
        lines = block.splitlines()
        # a setext heading is `Title` underlined by a run of `=` or `-`
        if len(lines) >= 2 and set(lines[1].strip()) in ({"="}, {"-"}):
            continue
        return " ".join(line.strip() for line in lines if line.strip())
    return None


def _title(kind: str, canonical_id: str, card_data: dict[str, Any]) -> str:
    """A dataset's human `pretty_name` when set, else the repo id."""
    if kind == "dataset":
        pretty = _clean(card_data.get("pretty_name"))
        if pretty:
            return pretty
    return canonical_id


def _canonical_url(kind: str, canonical_id: str) -> str:
    prefix = "datasets/" if kind == "dataset" else ""
    return f"{SITE_ROOT}/{prefix}{canonical_id}"


def _concepts(kind: str, data: dict[str, Any], card_data: dict[str, Any]) -> tuple[str, ...]:
    """Author-declared, semantic descriptors as deduped concepts.

    The task — a model's `pipeline_tag`, a dataset's `task_categories`
    (plus the finer `task_ids`) — and the author's `cardData.tags` (the
    github-topics parallel). The flat, auto-derived `tags` array is
    deliberately excluded.
    """
    values: list[Any] = []
    if kind == "dataset":
        values += _str_list(card_data.get("task_categories"))
        values += _str_list(card_data.get("task_ids"))
    else:
        values.append(data.get("pipeline_tag"))
    values += _str_list(card_data.get("tags"))
    return _dedupe(values)


def _tags(kind: str, data: dict[str, Any], card_data: dict[str, Any]) -> tuple[str, ...]:
    """The structured-facet slot: framework `library_name` (models) + license.

    The license is the structured taxonomy PyPI classifiers and SPDX
    licenses fill elsewhere; `library_name` (`transformers`, `diffusers`)
    is the framework facet, present only for models.
    """
    values: list[Any] = []
    if kind != "dataset":
        values.append(data.get("library_name"))
    values += _str_list(card_data.get("license"))
    return _dedupe(values)


def _links(tags_list: list[Any]) -> tuple[str, ...]:
    """Cross-reference prefixes in the flat tag array, as deduped links.

    `arxiv:<id>` → the paper's abstract page (resolved by `scrolls related`
    to the saved arXiv item — the model↔paper edge); `dataset:<name>` →
    the dataset's Hub page (the model↔dataset edge). Order-preserving.
    """
    links: list[str] = []
    for tag in tags_list:
        if not isinstance(tag, str):
            continue
        if tag.startswith("arxiv:"):
            value = tag[len("arxiv:"):].strip()
            if value:
                links.append(f"https://arxiv.org/abs/{value}")
        elif tag.startswith("dataset:"):
            value = tag[len("dataset:"):].strip()
            if value:
                links.append(f"{SITE_ROOT}/datasets/{value}")
    return tuple(dict.fromkeys(links))


def _str_list(value: Any) -> list[str]:
    """A scalar or list coerced to a list of non-empty trimmed strings.

    `cardData.license` is a string while `cardData.tags`/`task_categories`
    are lists; both reduce to the same shape here.
    """
    if isinstance(value, str):
        cleaned = _clean(value)
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        return [c for c in (_clean(v) for v in value) if c]
    return []


def _dedupe(values: Any) -> tuple[str, ...]:
    """Non-empty trimmed strings, order-preserving and deduped."""
    if not isinstance(values, list):
        return ()
    cleaned = (_clean(v) for v in values)
    return tuple(dict.fromkeys(v for v in cleaned if v))


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


_get_json = http.get_json
_get_text = http.get_text
