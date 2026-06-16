"""Shareable custody bundles (ADR 0103, MVP M4).

`scrolls export bundle <query>` writes one self-contained Markdown file an
agent can hand to a person or another library: a readable *briefing* on a
topic — best matches, each with its custody **fidelity** tier (ADR 0100) and
**provenance** — plus an embedded, sentinel-fenced **custody block** holding
the lossless canonical rows. `scrolls import bundle <path>` reads that block
back, reconstructing the index rows losslessly.

The bundle is the shareable complement to `export items` (ADR 0082): where
that is the whole-library/faceted JSONL *backup* (machine-oriented, streamed
to stdout), this is the *scoped, human-and-agent-readable briefing* — same
lossless core (the `item_to_dict` rows), a different envelope and audience. It
is also the re-importable complement to `scrolls context`, which is a lossy
excerpt bundle (no raw, no full provenance) built to drop into a model's
context, not to round-trip.

Two layers in one file:

1. A briefing body (Markdown) — title + scope, then one entry per in-scope
   scroll naming its id, source, fidelity tier, capture timestamp, link, a
   capped excerpt, and — when an engine classified it — *how the category was
   derived* (the `classification_provenance` view: `by`/`basis`/`confidence`,
   roadmap H35). A `concept`-scoped bundle also carries that concept's
   synthesized LLM summary and its `summary_provenance` (engine + freshness).
   This is what a human or agent *reads*, and it now carries provenance without
   anyone parsing the JSONL ("provenance travels with every result").
2. A custody block — the canonical rows as JSON Lines inside a ` ```jsonl `
   code fence, wrapped in the ADR 0102 sentinel (`@generated`…`@end`). This is
   what `import bundle` round-trips against; the JSONL is byte-identical to
   what `export items` writes, so the bundle's losslessness is the same already
   tested by ADR 0082/0099. The sentinel makes the block machine-locatable and
   lets the briefing body above and below it carry hand annotations a
   re-export won't clobber (the refresh-safe contract, ADR 0102).

Completeness is honest (the M2 contract): the bundle carries *every* scroll in
scope, never a truncated top-N — a take-it-with-you custody artifact must not
silently drop members. Re-import is custody-safe: rows go in with
`INSERT OR IGNORE` (ADR 0082), so importing a bundle never overwrites an item
the target library already holds; derived artifacts (scrolls, media, the
compiled `library/`) rebuild from the rows via `scrolls doctor --fix` / `kb`,
exactly as `import items` relies on.
"""

from __future__ import annotations

import json
from pathlib import Path

from scrolls.generated import GENERATED_END, fence, generated_body
from scrolls.items import (
    ScrollItem,
    classification_provenance,
    get_fidelity,
    get_item,
    item_from_dict,
    list_items,
)
from scrolls.items_export import dump_items_export
from scrolls.kb import ConceptSummary, group_concepts, load_concept_summaries
from scrolls.kb_llm import members_hash, summary_provenance
from scrolls.render import slugify
from scrolls.search import count_matches, search_items

_EXCERPT_CHARS = 600
_REGENERATED_BY = "scrolls export bundle"

# An item with no id/source/url/saved_at isn't a Scrolls item — mirror the
# items-export validation so a corrupt custody block fails loudly, not silently.
_REQUIRED = ("id", "source", "url", "saved_at")


class BundleError(Exception):
    """A file is not a Scrolls custody bundle, or its custody block is corrupt."""


def build_bundle(
    db_path: Path,
    query: str,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> str:
    """Render the self-contained custody bundle for a query (briefing + block).

    Scope is the same query + facets every read surface uses (`search_items`),
    so a bundle covers exactly what a `context`/`search` of the same scope
    would — but with no cap: it carries every matching scroll (`count_matches`
    is the limit), because a custody artifact must be complete about its scope,
    not a top-N (the M2 completeness contract). Raises ValueError on a blank
    query, like `scrolls context`. No matches still yields a valid bundle (an
    empty custody block) so an agent never crashes on an empty scope.
    """
    # the honest denominator past any cap (also validates the query, raising on
    # blank) — used here as the limit so the bundle holds the *whole* scope
    matched = count_matches(
        db_path,
        query,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )
    hits = search_items(
        db_path,
        query,
        limit=max(matched, 1),
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )
    items = [item for item in (get_item(db_path, hit.id) for hit in hits) if item]

    title = f"# Scrolls Custody Bundle: {query}"
    scope = _scope_note(source, category, stage, tag, concept)
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    # a concept-scoped bundle is *about* that concept, so its synthesized
    # summary and how that summary was derived belong in the briefing (H35)
    if concept is not None:
        lines += _concept_summary_block(db_path, concept)

    if not items:
        lines += ["No matching scrolls.", ""]
    else:
        lines += [
            f"_{len(items)} scroll(s), the whole scope — self-contained. "
            "Re-import losslessly with `scrolls import bundle <file>`. Each "
            "scroll's full custody record (raw text, provenance, fidelity) "
            "travels in the fenced block below._",
            "",
        ]
        for rank, item in enumerate(items, start=1):
            lines += _briefing_entry(rank, item)

    # the lossless custody block: the same JSONL `export items` writes, inside a
    # code fence, inside the ADR 0102 sentinel so it is locatable and the body
    # around it stays hand-annotatable across a re-export
    jsonl = dump_items_export(items)
    block = f"```jsonl\n{jsonl}```"
    lines += [fence(block, _REGENERATED_BY).rstrip("\n")]
    return "\n".join(lines) + "\n"


def parse_bundle(text: str) -> list[ScrollItem]:
    """Reconstruct the items from a bundle's custody block; the export inverse.

    Reads the sentinel-fenced custody block (ADR 0102), strips the ` ```jsonl `
    code fence, and parses each record the same way `import items` does
    (`item_from_dict`, required identity fields enforced, unknown keys tolerated
    for forward compatibility). Raises BundleError when the text carries no
    custody block (not a bundle) or a record is malformed, naming the record so
    corruption is locatable rather than silently dropped — losing a record from
    a custody artifact would lose data without telling anyone.
    """
    body = generated_body(text)
    if body is None:
        raise BundleError(
            "not a Scrolls custody bundle: no custody block "
            f"(expected an `@generated`…`{GENERATED_END}` region)"
        )
    items: list[ScrollItem] = []
    record_no = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):  # blank or the code-fence lines
            continue
        record_no += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleError(
                f"custody block record {record_no}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise BundleError(
                f"custody block record {record_no}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _REQUIRED if not data.get(name)]
        if missing:
            raise BundleError(
                f"custody block record {record_no}: missing required field(s): "
                + ", ".join(missing)
            )
        items.append(item_from_dict(data))
    return items


def _briefing_entry(rank: int, item: ScrollItem) -> list[str]:
    """The readable per-scroll briefing block: identity, custody facts, excerpt."""
    out = [f"## {rank}. {item.title or item.id} (`{item.id}`)", ""]
    facts = f"- {item.source} · fidelity `{get_fidelity(item)}` · stage `{item.stage}`"
    out.append(facts)
    out.append(f"- captured {item.saved_at}")
    out.append(f"- {item.canonical_url or item.url}")
    if item.content_hash:
        out.append(f"- content-hash `{item.content_hash}`")
    classification = _classification_line(item)
    if classification:
        out.append(classification)
    excerpt = _excerpt(item)
    if excerpt:
        out += ["", excerpt]
    out.append("")
    return out


def _classification_line(item: ScrollItem) -> str | None:
    """How the item's category was derived — the classification view, made readable.

    Renders the same derived `classification_provenance` view `list`/`show`/
    `search` carry (roadmap H20/H21/H26) into one briefing line, so a reader of
    the bundle sees *how the category was produced* (`by`/`basis`/`confidence`)
    without parsing the embedded JSONL — "provenance travels with every result"
    on the readable side too (roadmap H35). Returns None when no engine stamped
    the category — an unclassified or user-set item — the same honest absence the
    structured surfaces keep: no method is claimed for a category no engine
    produced, so the line is simply omitted (the row's shape stays stable).

    The ruleset *fingerprint* the view also carries (`ruleset`) is deliberately
    left out: it is the re-derivation key (in the JSONL block for that), not
    reading material, and `confidence.freshness` already reports what it implies.
    """
    view = classification_provenance(item)
    if view is None:
        return None
    detail = view.get("basis") or (
        f"model {view['model']}" if view.get("model") else None
    )
    head = f"classified `{item.category}` by `{view['by']}`"
    if detail:
        head += f" ({detail})"
    confidence = view["confidence"]
    marker = confidence["level"]
    if "freshness" in confidence:
        marker += f", {confidence['freshness']}"
    return f"- {head} · confidence {marker}"


def _concept_summary_block(db_path: Path, concept: str) -> list[str]:
    """The bundled concept's synthesized summary + its provenance, when one exists.

    The summary-axis counterpart of `_classification_line` (roadmap H35): for a
    `concept`-scoped bundle the bundle is *about* that concept, so its stored LLM
    concept summary (ADR 0025) — and how that summary was derived — belongs in
    the readable briefing. Freshness is computed against the concept's *whole*
    live membership (`summary_provenance`/`summary_freshness`), not the bundle's
    query-filtered subset, because a summary is a synthesis of the entire concept;
    filtering the members for a bundle does not change whether a re-synthesis
    would reproduce the stored summary.

    Returns [] when the concept has no stored summary — honest absence
    (`summary_provenance` returns None), no synthesis claimed for one that does
    not exist. The summary text here is a *readable derived view*, not part of
    the lossless custody block: only the item rows in the `@generated` JSONL
    round-trip through `import bundle` (the round-trip invariant H35 leaves
    untouched).
    """
    slug = slugify(concept)
    if not slug:
        return []
    stored: ConceptSummary | None = load_concept_summaries(db_path).get(slug)
    if stored is None:
        return []
    rendered = [item for item in list_items(db_path) if item.markdown_path]
    entry = group_concepts(rendered).get(slug)
    live = members_hash(entry["items"]) if entry else ""
    view = summary_provenance(stored, live)
    if view is None:  # unreachable while `stored` is set, but keeps the contract local
        return []
    return [
        f"**Concept summary** — {stored.summary}",
        "",
        f"_Summary by `{view['by']}`, {view['freshness']} "
        f"(members fingerprint `{view['members_hash'][:12]}`)._",
        "",
    ]


def _scope_note(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
) -> str:
    """A `source=…, category=…` summary of the active facets, else '' (as `context`)."""
    parts = []
    if source is not None:
        parts.append(f"source={source}")
    if category is not None:
        parts.append(f"category={category or 'unclassified'}")
    if stage is not None:
        parts.append(f"stage={stage}")
    if tag is not None:
        parts.append(f"tag={tag}")
    if concept is not None:
        parts.append(f"concept={concept}")
    return ", ".join(parts)


def _excerpt(item: ScrollItem) -> str:
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
