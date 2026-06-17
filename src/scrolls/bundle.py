"""Shareable custody bundles (ADR 0103, MVP M4).

`scrolls export bundle <query>` writes one self-contained Markdown file an
agent can hand to a person or another library: a readable *briefing* on a
topic — best matches, each with its custody **fidelity** tier (ADR 0100) and
**provenance** — plus an embedded, sentinel-fenced **custody block** holding
the lossless canonical rows. `scrolls import bundle <path>` reads that block
back, reconstructing the index rows losslessly.

Two output forms (`--format`, roadmap H39): the **Markdown** bundle
(`build_bundle`) is the canonical, lossless, re-importable artifact this module's
round-trip rests on; the **HTML** bundle (`build_bundle_html`) renders the same
scope and per-scroll custody picture as a self-contained, browser-readable
briefing — the human-facing **read** form, *export-only* (its embedded custody
JSONL is present but `import bundle` consumes the Markdown form; no false
round-trip claim). Both share `_gather_scope` and the custody/provenance
primitives, so they cannot disagree.

The bundle is the shareable complement to `export items` (ADR 0082): where
that is the whole-library/faceted JSONL *backup* (machine-oriented, streamed
to stdout), this is the *scoped, human-and-agent-readable briefing* — same
lossless core (the `item_to_dict` rows), a different envelope and audience. It
is also the re-importable complement to `scrolls context`, which is a lossy
excerpt bundle (no raw, no full provenance) built to drop into a model's
context, not to round-trip.

Two layers in one file:

1. A briefing body (Markdown) — title + scope, a one-line scope **custody
   headline** (N scrolls, fidelity-tier counts, drift-posture counts — how
   custody stands across the whole bundle, roadmap H45; totals equal the entries
   and `doctor`'s `custody` aggregate for the scope by construction), then one
   entry per in-scope scroll naming its id, source, fidelity tier, capture
   timestamp, link, a capped excerpt, its custody **drift posture** from the
   verify ledger
   (`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H42 — the same
   `latest_events` doctor's `custody.drift` aggregates, so they cannot disagree),
   and — when an engine classified it — *how the category was derived* (the
   `classification_provenance` view: `by`/`basis`/`confidence`, roadmap H35). A
   `concept`-scoped bundle also carries that concept's synthesized LLM summary
   and its `summary_provenance` (engine + freshness). This is what a human or
   agent *reads*, and it now carries provenance and custody posture without
   anyone parsing the JSONL ("provenance travels with every result").
2. A custody block — the canonical rows as JSON Lines inside a ` ```jsonl `
   code fence, wrapped in the ADR 0102 sentinel (`@generated`…`@end`). This is
   what `import bundle` round-trips against; the JSONL is byte-identical to
   what `export items` writes, so the bundle's losslessness is the same already
   tested by ADR 0082/0099. The sentinel makes the block machine-locatable and
   lets the briefing body above and below it carry hand annotations a
   re-export won't clobber (the refresh-safe contract, ADR 0102).
3. A custody-events block (roadmap H67) — the in-scope items' verify ledger
   (`custody_events`) as a second sibling `@generated` JSONL region, so an
   item's drift *history* travels, not just the exporter's last-seen posture
   frozen in the briefing prose: "lossless round-trip is a guarantee" (custody
   vision) extended from the item to its custody record. `import bundle`
   restores it with an idempotent, content-keyed dedup (`custody.import_events`)
   so a re-import is a custody no-op. The items block stays the first region and
   byte-identical to `export items`, so its round-trip is untouched; a pre-H67
   bundle simply has no second region and imports items only.

Completeness is honest (the M2 contract): the bundle carries *every* scroll in
scope, never a truncated top-N — a take-it-with-you custody artifact must not
silently drop members. Re-import is custody-safe: rows go in with
`INSERT OR IGNORE` (ADR 0082), so importing a bundle never overwrites an item
the target library already holds; derived artifacts (scrolls, media, the
compiled `library/`) rebuild from the rows via `scrolls doctor --fix` / `kb`,
exactly as `import items` relies on.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from scrolls.custody import (
    CustodyEvent,
    custody_headline,
    drift_posture,
    dump_events_export,
    event_from_dict,
    events_for_items,
    latest_events,
)
from scrolls.generated import GENERATED_END, fence, generated_bodies, generated_body
from scrolls.items import (
    ScrollItem,
    classification_phrase,
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
# the sibling custody-events block's label, so a reader can tell the two
# `@generated` regions apart (roadmap H67 — portable custody)
_EVENTS_REGENERATED_BY = "scrolls export bundle (custody events)"

# An item with no id/source/url/saved_at isn't a Scrolls item — mirror the
# items-export validation so a corrupt custody block fails loudly, not silently.
_REQUIRED = ("id", "source", "url", "saved_at")
# A custody event with no item_id/checked_at/status isn't a ledger row — the
# minimal identity an event must carry to be restorable (roadmap H67).
_EVENT_REQUIRED = ("item_id", "checked_at", "status")

# Inline stylesheet for the HTML briefing (roadmap H39) — kept in the document so
# the file is self-contained and offline (no external CSS/JS, nothing fetched
# from the network). `color-scheme` follows the reader's light/dark preference.
_HTML_STYLE = """\
:root { color-scheme: light dark; }
body { font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
       sans-serif; max-width: 48rem; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.6rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; padding-top: 1rem;
     border-top: 1px solid rgba(127,127,127,.3); }
code { background: rgba(127,127,127,.15); padding: .1em .3em; border-radius: 3px;
       font-size: .9em; }
.custody-headline { font-weight: 600; }
.note { color: #6a6a6a; font-size: .85rem; }
.custody-facts { list-style: none; padding-left: 0; }
.custody-facts li { margin: .15rem 0; }
.excerpt { border-left: 3px solid rgba(127,127,127,.4); margin: .5rem 0;
           padding: .25rem 0 .25rem 1rem; }
details.custody-data { margin-top: 2rem; }
details.custody-data pre { overflow-x: auto; padding: 1rem; border-radius: 4px;
                           background: rgba(127,127,127,.1); font-size: .8rem; }
"""


class BundleError(Exception):
    """A file is not a Scrolls custody bundle, or its custody block is corrupt."""


def _gather_scope(
    db_path: Path,
    query: str,
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
) -> tuple[list[ScrollItem], dict[str, CustodyEvent], list[CustodyEvent]]:
    """Resolve the bundle scope once, for both the Markdown and HTML renderers.

    Returns the in-scope items (every match, no cap — `count_matches` is the
    limit, the M2 completeness contract), the latest custody verdict per item
    (`latest_events`, one read for the whole scope, the drift-posture source),
    and the in-scope verify ledger (`events_for_items`, the portable custody
    events, roadmap H67). `count_matches` also validates the query, raising
    ValueError on a blank one. The ledger reads are skipped when there is
    nothing to brief (no items, incl. a missing library) so an empty/pre-init
    bundle stays valid in either format.
    """
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
    verdicts = latest_events(db_path) if items else {}
    events = events_for_items(db_path, [item.id for item in items]) if items else []
    return items, verdicts, events


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

    This is the **canonical, lossless re-import unit**: the Markdown form
    `scrolls import bundle` round-trips against. The browser-readable HTML form
    (`build_bundle_html`, roadmap H39) is export-only.
    """
    # one ledger read for the whole scope: the latest custody verdict per item,
    # so each briefing entry can name its drift posture (H42) from the same
    # `latest_events` doctor aggregates — no per-item query, no disagreement.
    items, verdicts, events = _gather_scope(
        db_path, query, source, category, stage, tag, concept
    )

    title = f"# Scrolls Custody Bundle: {query}"
    scope = _scope_note(source, category, stage, tag, concept)
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    # the scope-level custody headline (roadmap H45): one line summarising how
    # custody stands across the *whole* bundle — N scrolls, fidelity tiers, drift
    # postures — so a reader gauges the scope without scanning every entry. Its
    # totals equal the per-scroll entries by construction (same get_fidelity +
    # drift_posture), the H42 convergence at scope level.
    lines += [custody_headline(items, verdicts), ""]
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
            "scroll's full custody record (raw text, provenance, fidelity) and "
            "its verify-ledger custody events travel in the fenced blocks "
            "below._",
            "",
        ]
        for rank, item in enumerate(items, start=1):
            lines += _briefing_entry(rank, item, verdicts.get(item.id))

    # the lossless custody block + the sibling custody-events block — the same
    # sentinel-fenced JSONL the HTML form embeds, so the two formats carry
    # byte-identical custody data (the round-trip stays a Markdown property)
    lines += [_items_block(items)]
    lines += [_events_block(events)]
    return "\n".join(lines) + "\n"


def _items_block(items: list[ScrollItem]) -> str:
    """The lossless custody block: the same JSONL `export items` writes, inside a
    code fence, inside the ADR 0102 sentinel so it is locatable and the body
    around it stays hand-annotatable across a re-export."""
    block = f"```jsonl\n{dump_items_export(items)}```"
    return fence(block, _REGENERATED_BY).rstrip("\n")


def _events_block(events: list[CustodyEvent]) -> str:
    """The sibling custody-events block (roadmap H67): the in-scope items' verify
    ledger so their drift *history* travels, not just the exporter's last-seen
    posture frozen in the briefing prose. A second `@generated` region (the items
    block stays byte-identical to `export items`, so its round-trip is the same
    already-tested property); `import bundle` restores it deduped. An unverified
    scope has no events — an empty block, the same shape an empty items block
    takes — so the bundle's structure is stable."""
    block = f"```jsonl\n{dump_events_export(events)}```"
    return fence(block, _EVENTS_REGENERATED_BY).rstrip("\n")


def build_bundle_html(
    db_path: Path,
    query: str,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> str:
    """Render the scoped custody bundle as a self-contained, offline HTML briefing.

    The browser-readable, human-facing **read** counterpart of `build_bundle`
    (roadmap H39): the same scope (every match, no cap — `_gather_scope`) and the
    same per-scroll custody picture — fidelity tier, drift posture, classification
    provenance, and (for a `--concept` bundle) the synthesized summary — rendered
    into one self-contained HTML file (inline CSS, no scripts, nothing fetched
    from the network). All dynamic content is HTML-escaped, so a tag-bearing
    title or body can never inject markup.

    **Export-only — not a re-import unit.** The canonical lossless round-trip
    stays a property of the Markdown form (`build_bundle`/`import bundle`); the
    HTML embeds the *same* sentinel-fenced custody + custody-events JSONL (the
    shared `_items_block`/`_events_block`) in `<details>`/`<pre>` so the data is
    *present* for a reader, but `import bundle` consumes the Markdown bundle. The
    briefing says so, to make no false round-trip claim. Raises ValueError on a
    blank query, like `build_bundle`.
    """
    items, verdicts, events = _gather_scope(
        db_path, query, source, category, stage, tag, concept
    )

    scope = _scope_note(source, category, stage, tag, concept)
    heading = f"Scrolls Custody Bundle: {query}"
    title = heading + (f" ({scope})" if scope else "")

    body = [f"<h1>{html.escape(title)}</h1>"]
    # the scope custody headline, from the shared `custody_headline` primitive
    # (sans the markdown `_` emphasis) — so the HTML headline content is identical
    # to the Markdown briefing's and to `status`/`context`/`doctor` (H45/H47)
    headline = custody_headline(items, verdicts).strip("_")
    body.append(f'<p class="custody-headline">{html.escape(headline)}</p>')
    body.append(
        '<p class="note">Read-only briefing. The canonical lossless re-import '
        "unit is the <strong>Markdown</strong> bundle (<code>scrolls export "
        "bundle … --format markdown</code>); the custody rows below are embedded "
        "for reference and re-imported via the Markdown form with <code>scrolls "
        "import bundle</code>.</p>"
    )
    # a concept-scoped bundle is *about* that concept, so its synthesized summary
    # and how it was derived belong in the briefing (H35), same as the Markdown
    if concept is not None:
        body += _concept_summary_html(db_path, concept)

    if not items:
        body.append("<p>No matching scrolls.</p>")
    else:
        body.append(
            f"<p>{len(items)} scroll(s), the whole scope — self-contained.</p>"
        )
        for rank, item in enumerate(items, start=1):
            body += _briefing_entry_html(rank, item, verdicts.get(item.id))

    # the same sentinel-fenced custody blocks the Markdown form carries, embedded
    # (escaped) so the lossless data travels in the HTML too — but it is not a
    # re-import unit (the round-trip stays a Markdown property)
    body.append(_custody_details_html("Custody block", _items_block(items), len(items)))
    body.append(
        _custody_details_html("Custody events", _events_block(events), len(events))
    )
    return _html_document(title, body)


def _html_document(title: str, body: list[str]) -> str:
    """Wrap the briefing body in a self-contained HTML5 document with inline CSS."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{_HTML_STYLE}</style>\n"
        "</head>\n<body>\n<main>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def _briefing_entry_html(
    rank: int, item: ScrollItem, verdict: CustodyEvent | None
) -> list[str]:
    """The HTML twin of `_briefing_entry`: identity, custody facts, excerpt."""
    out = [
        '<section class="scroll">',
        f"<h2>{rank}. {html.escape(item.title or item.id)} "
        f"(<code>{html.escape(item.id)}</code>)</h2>",
        '<ul class="custody-facts">',
        f"<li>{html.escape(item.source)} · fidelity "
        f"<code>{html.escape(get_fidelity(item))}</code> · stage "
        f"<code>{html.escape(item.stage)}</code></li>",
        f"<li>captured {html.escape(item.saved_at)}</li>",
    ]
    url = item.canonical_url or item.url
    out.append(
        f'<li><a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></li>'
    )
    if item.content_hash:
        out.append(f"<li>content-hash <code>{html.escape(item.content_hash)}</code></li>")
    out.append(f"<li>{_drift_html(verdict)}</li>")
    classification = _classification_html(item)
    if classification:
        out.append(f"<li>{classification}</li>")
    out.append("</ul>")
    excerpt = _excerpt(item)
    if excerpt:
        out.append(f'<blockquote class="excerpt">{html.escape(excerpt)}</blockquote>')
    out.append("</section>")
    return out


def _drift_html(verdict: CustodyEvent | None) -> str:
    """The per-scroll drift posture as HTML — the twin of `_drift_line` (H42).

    Reads the same `custody.drift_posture` + `_POSTURE_GLOSS` the Markdown line
    does, so the HTML posture word and `doctor`'s `custody.drift` cannot disagree;
    ``unverified`` is stated explicitly, never silently "clean".
    """
    posture = drift_posture(verdict)
    if verdict is None:
        return "custody <code>unverified</code> — never re-checked against its source"
    return (
        f"custody <code>{html.escape(posture)}</code> "
        f"({html.escape(_POSTURE_GLOSS[posture])}) as of {html.escape(verdict.checked_at)}"
    )


def _classification_html(item: ScrollItem) -> str | None:
    """How the category was derived, as HTML — the twin of `_classification_line`.

    Renders the *same* shared `classification_phrase` the Markdown briefing and
    every structured surface use (H35/H44), with its backtick `code` spans turned
    into `<code>` (`_inline_code`), so the method/confidence reads identically.
    Returns None for an unclassified or user-set category — the same honest
    absence (no method claimed for a category no engine produced).
    """
    view = classification_provenance(item)
    if view is None:
        return None
    return (
        f"classified <code>{html.escape(item.category)}</code> "
        f"{_inline_code(classification_phrase(view))}"
    )


def _inline_code(text: str) -> str:
    """Escape HTML and render markdown `code` spans as `<code>`.

    Used only on the controlled `classification_phrase` — its backtick spans are
    engine/basis/confidence tokens, never user content — so the HTML reads the
    same method/confidence as every other surface without a markdown renderer.
    """
    return "".join(
        f"<code>{html.escape(part)}</code>" if i % 2 else html.escape(part)
        for i, part in enumerate(text.split("`"))
    )


def _custody_details_html(label: str, fenced_block: str, count: int) -> str:
    """A collapsible `<details>` holding one sentinel-fenced custody block (escaped).

    The lossless JSONL is *present* in the HTML (so a reader can extract it), but
    the block is the Markdown form's content embedded verbatim and escaped — not a
    re-import surface; `import bundle` consumes the Markdown bundle (H39).
    """
    return (
        f'<details class="custody-data"><summary>{html.escape(label)} — '
        f"{count} row(s)</summary>\n<pre>{html.escape(fenced_block)}</pre>\n</details>"
    )


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


def parse_bundle_events(text: str) -> list[CustodyEvent]:
    """Reconstruct the custody events from a bundle's custody-events block.

    The verify-ledger counterpart of `parse_bundle` (roadmap H67): reads the
    *second* `@generated` region (the items block is the first), strips the
    ` ```jsonl ` code fence, and parses each row through `event_from_dict`.
    Returns ``[]`` when the bundle carries no second region — a **pre-H67
    bundle** with only the items block, so its events simply do not travel (the
    prior behavior), or a present-but-empty events block (an unverified scope).
    Raises BundleError on a malformed row, naming the record, so a corrupt
    custody ledger fails loudly rather than silently dropping a check — losing
    drift history from a custody artifact would lose the proof of *when* a source
    was verified.
    """
    bodies = generated_bodies(text)
    if len(bodies) < 2:  # only the items block (a pre-H67 bundle) — no events
        return []
    events: list[CustodyEvent] = []
    record_no = 0
    for raw in bodies[1].splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):  # blank or the code-fence lines
            continue
        record_no += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleError(
                f"custody-events block record {record_no}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise BundleError(
                f"custody-events block record {record_no}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _EVENT_REQUIRED if not data.get(name)]
        if missing:
            raise BundleError(
                f"custody-events block record {record_no}: missing required "
                "field(s): " + ", ".join(missing)
            )
        events.append(event_from_dict(data))
    return events


def _briefing_entry(
    rank: int, item: ScrollItem, verdict: CustodyEvent | None
) -> list[str]:
    """The readable per-scroll briefing block: identity, custody facts, excerpt."""
    out = [f"## {rank}. {item.title or item.id} (`{item.id}`)", ""]
    facts = f"- {item.source} · fidelity `{get_fidelity(item)}` · stage `{item.stage}`"
    out.append(facts)
    out.append(f"- captured {item.saved_at}")
    out.append(f"- {item.canonical_url or item.url}")
    if item.content_hash:
        out.append(f"- content-hash `{item.content_hash}`")
    out.append(_drift_line(verdict))
    classification = _classification_line(item)
    if classification:
        out.append(classification)
    excerpt = _excerpt(item)
    if excerpt:
        out += ["", excerpt]
    out.append("")
    return out


# A reader-facing gloss per posture; the bare posture word is the convergence
# token (`custody \`<posture>\``) doctor's `custody.drift` counts agree with.
_POSTURE_GLOSS = {
    "verified": "confirmed unchanged at the last verify",
    "drifted": "source changed since capture — raw preserved, drift is a recorded event",
    "rotted": "source gone upstream — this is the last held copy",
    "error": "last re-check could not reach the source",
}


def _drift_line(verdict: CustodyEvent | None) -> str:
    """The per-scroll custody drift posture, from the verify ledger (roadmap H42).

    The posture an agent reading a shared briefing most needs to weigh: was this
    scroll confirmed unchanged, never re-checked, or has its source drifted/rotted
    since capture? Derived through the one shared `custody.drift_posture`, so the
    briefing posture and `doctor`'s `custody.drift` aggregate read the same ledger
    and cannot disagree. ``unverified`` is stated explicitly (never silently
    omitted) — "absent from the drift counts" must never be read as "confirmed
    unchanged" (the drift block's honesty, on the per-scroll axis). A drifted or
    rotted scroll is still carried losslessly in the custody block below: raw is
    sacred, drift is a *recorded posture*, never a reason to drop the scroll.
    """
    posture = drift_posture(verdict)
    if verdict is None:
        return "- custody `unverified` — never re-checked against its source"
    return (
        f"- custody `{posture}` ({_POSTURE_GLOSS[posture]}) "
        f"as of {verdict.checked_at}"
    )


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
    The method/confidence rendering is the shared `classification_phrase`, so this
    briefing line and the `scrolls context` per-excerpt tag (H44) read identically.
    """
    view = classification_provenance(item)
    if view is None:
        return None
    return f"- classified `{item.category}` {classification_phrase(view)}"


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
    result = _concept_summary_view(db_path, concept)
    if result is None:
        return []
    stored, view = result
    return [
        f"**Concept summary** — {stored.summary}",
        "",
        f"_Summary by `{view['by']}`, {view['freshness']} "
        f"(members fingerprint `{view['members_hash'][:12]}`)._",
        "",
    ]


def _concept_summary_html(db_path: Path, concept: str) -> list[str]:
    """The HTML twin of `_concept_summary_block` — the concept's summary + provenance."""
    result = _concept_summary_view(db_path, concept)
    if result is None:
        return []
    stored, view = result
    return [
        '<section class="concept-summary">',
        f"<p><strong>Concept summary</strong> — {html.escape(stored.summary)}</p>",
        f'<p class="note">Summary by <code>{html.escape(view["by"])}</code>, '
        f"{html.escape(view['freshness'])} (members fingerprint "
        f"<code>{html.escape(view['members_hash'][:12])}</code>).</p>",
        "</section>",
    ]


def _concept_summary_view(
    db_path: Path, concept: str
) -> tuple[ConceptSummary, dict] | None:
    """The bundled concept's stored summary + its `summary_provenance` view, or None.

    Shared by the Markdown (`_concept_summary_block`) and HTML
    (`_concept_summary_html`) renderers so both report the same synthesis and
    freshness. Freshness is computed against the concept's *whole* live membership
    (not the bundle's query-filtered subset), because a summary is a synthesis of
    the entire concept. Returns None for an unknown concept, no stored summary, or
    an empty slug — the honest absence both renderers turn into [].
    """
    slug = slugify(concept)
    if not slug:
        return None
    stored: ConceptSummary | None = load_concept_summaries(db_path).get(slug)
    if stored is None:
        return None
    rendered = [item for item in list_items(db_path) if item.markdown_path]
    entry = group_concepts(rendered).get(slug)
    live = members_hash(entry["items"]) if entry else ""
    view = summary_provenance(stored, live)
    if view is None:  # unreachable while `stored` is set, but keeps the contract local
        return None
    return stored, view


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
