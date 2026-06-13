"""Wikidata fetch adapter — structured knowledge (ADR 0075).

Wikidata is the structured-knowledge sibling of Wikipedia: where the Wikipedia
adapter (ADR 0002) fetches an article's *prose*, Wikidata holds the same world as
a graph of **entities** (`Q<digits>`) — each a labelled, described node with type
relations and sitelinks back to the Wikipedia articles about it. A saved
`wikidata.org/wiki/Q42` link used to fall through to `web`, a `trafilatura` scrape
of a JS-rendered page that produced no concepts and no edge to the Wikipedia
article it describes — the concept-poor island dev.to/RFC/books were before their
adapters (ADR 0061/0066/0073). One keyless GET against the canonical entity-data
view returns the whole entity — no auth, no runtime dependency (the
arXiv/Crossref/Open Library discipline, ADR 0008/0037/0073).

Three platform facts shape the output:

1. **The type relations are the concepts.** An entity's `P31` (*instance of*) and
   `P279` (*subclass of*) statements are its place in Wikidata's ontology — the
   structured "what kind of thing is this" signal, the direct analog of the
   Wikipedia adapter's page categories → `concepts` (ADR 0002) and of github
   topics / MeSH / Open Library subjects (ADR 0007/0065/0073). Their *values* are
   themselves QIDs (`Q5`, not "human"), so they are resolved to labels with one
   batched `wbgetentities&props=labels` request — the Open Library author-key
   resolution (ADR 0073), economized into a single call however many types an
   entity has. A failed resolution degrades to no concepts rather than failing the
   fetch. Richer property-specific concepts (occupation `P106`, field of work
   `P101`, genre `P136`) are deferred to keep the property set principled and
   bounded — the type hierarchy is the one universal, ontological signal.

2. **The label is the title, the description is the summary; there is no full
   text.** Wikidata stores no prose body, so a Wikidata scroll is honestly
   summary-only with **no `extracted_text`** (the Crossref/PubMed/Open Library
   metadata-only shape, ADR 0037/0065/0073). Labels and descriptions are
   per-language; the title prefers the English label then the script-agnostic
   `mul` label Wikidata now mints for names that read the same across languages
   (so `Q42`'s "Douglas Adams", stored under `mul` with no `en`, is still found),
   the summary the English then `mul` description. Tags stay empty by design — a
   Wikidata entity has no clean controlled facet like an RFC's status or a
   package's license (the go/rubygems/Open Library posture, ADR 0042/0040/0073).

3. **The sitelinks are cross-source edges.** The English Wikipedia sitelink
   becomes an `en.wikipedia.org` `link` — the **Wikidata↔Wikipedia edge** that
   `scrolls related`/`graph` resolves to the saved Wikipedia scroll for the same
   subject (the model↔paper / edition↔work edge of ADR 0041/0073). The entity's
   official website (`P856`) becomes an outbound `link` too. Other-language
   sitelinks are deferred to keep `links` bounded (an entity can carry 200+).

The representative image (`P18`, a Wikimedia Commons filename) becomes a
`thumbnail` media ref on `commons.wikimedia.org/wiki/Special:FilePath/<file>` (the
Open Library cover convention, ADR 0073/0011). A Wikidata entity classifies as
`reference` — the structured sibling of a Wikipedia article, an entry to consult
(ADR 0075, the classify rule). Because an entity can be enormous (a popular item
carries every language's label and hundreds of sitelinks), `raw_text` keeps only
the projection the adapter consumed — the en/`mul` labels and descriptions, the
four claim properties it reads, and the English sitelink — rather than the whole
multi-hundred-KB record, so the index stays lean while still rebuildable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode

from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

SITE = "https://www.wikidata.org"
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath"
ENWIKI = "https://en.wikipedia.org/wiki"

GetJson = Callable[[str], dict[str, Any]]

# A Wikidata item id is `Q` + digits; the adapter only fetches Q items.
_QID = re.compile(r"Q\d+")
# The type relations whose values become concepts: P31 (instance of) names what an
# entity *is*, P279 (subclass of) what a class entity *generalizes*. Ordered, so an
# entity's direct type leads its superclasses.
_TYPE_PROPERTIES = ("P31", "P279")
# An entity carries few types in practice; the cap bounds a pathological item and
# stays under the wbgetentities 50-id limit so the resolution is always one call.
_MAX_TYPES = 20
# Languages preferred for a label/description, in order. `mul` is Wikidata's
# script-agnostic "multilingual" label, now the home of a name that reads the same
# across languages (so a person's name may live there with no `en`), checked after
# the English label proper.
_PREFERRED_LANGS = ("en", "mul")


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Wikidata entity; return it at stage 'fetched'.

    Reads the canonical entity-data view (`/wiki/Special:EntityData/<QID>.json`)
    for the entity, then one batched `wbgetentities` call to resolve its type
    QIDs to concept labels. Raises FetchError when the id is missing/not a Q item,
    the request fails, or the response holds no usable entity. The concept
    resolution degrades to no concepts rather than failing. The input item is
    never mutated.
    """
    get_json = get_json or _get_json
    qid = (item.source_id or "").upper()
    if not _QID.fullmatch(qid):
        raise FetchError(f"cannot determine Wikidata entity for item {item.id!r}")

    try:
        payload = get_json(f"{SITE}/wiki/Special:EntityData/{qid}.json")
    except (OSError, ValueError) as exc:
        raise FetchError(f"wikidata API request failed: {exc}") from exc

    entity = _entity(payload, qid)
    if entity is None:
        raise FetchError(f"wikidata entity not found: {qid}")
    # A redirected/merged QID resolves to its target, so trust the record's own id.
    canonical_id = _clean(entity.get("id")) or qid

    summary = _best_text(entity.get("descriptions"))
    raw = json.dumps(_projection(entity, canonical_id), sort_keys=True, ensure_ascii=False)
    hashed = summary or raw
    return replace(
        item,
        title=_best_text(entity.get("labels")) or item.title,
        canonical_url=f"{SITE}/wiki/{canonical_id}",
        raw_text=raw,
        extracted_text=None,  # Wikidata holds structured facts, not a prose body
        summary=summary,
        concepts=_concepts(entity, get_json),
        # `tags` is left untouched — Wikidata has no clean controlled facet of its
        # own (by design), so the adapter contributes none and any tags an import
        # seeded (browser-bookmark folder ancestry, ADR 0030) survive the fetch,
        # the wikipedia/Open Library omission rather than go's overwrite-with-empty.
        links=_links(entity),
        media=_media(entity),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "wikidata",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "wikidata:entitydata",
        },
        stage="fetched",
    )


def _entity(payload: Any, qid: str) -> dict[str, Any] | None:
    """The entity dict for `qid` from an entity-data payload, else None.

    The payload is `{"entities": {"<QID>": {...}}}`. The requested QID is the
    common key, but a redirected/merged id returns the *target* entity under its
    own key, so a missing exact key falls back to the single entity present.
    """
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, dict) or not entities:
        return None
    entity = entities.get(qid)
    if not isinstance(entity, dict):
        entity = next(iter(entities.values()), None)
    return entity if isinstance(entity, dict) and entity.get("id") else None


def _best_text(values: Any) -> str | None:
    """A label/description value, preferring `en`, then `mul`, then any.

    Wikidata stores labels/descriptions as `{lang: {"language": …, "value": …}}`.
    The English value is preferred, then the script-agnostic `mul` label (now the
    home of a name shared across languages — `Q42`'s "Douglas Adams" lives there
    with no `en`), then any other `en-*` variant, then any value at all, so an
    entity labelled only in another language still gets an honest title.
    """
    if not isinstance(values, dict):
        return None
    for lang in _PREFERRED_LANGS:
        text = _clean(_lang_value(values.get(lang)))
        if text:
            return text
    for lang, value in values.items():
        if isinstance(lang, str) and lang.startswith("en"):
            text = _clean(_lang_value(value))
            if text:
                return text
    for value in values.values():
        text = _clean(_lang_value(value))
        if text:
            return text
    return None


def _lang_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else None


def _concepts(entity: dict[str, Any], get_json: GetJson) -> tuple:
    """The entity's type relations resolved to concept labels (bounded, degrading).

    Collects the QID values of the `P31`/`P279` statements, then resolves them all
    to labels in one batched `wbgetentities&props=labels` request (the Open Library
    author-key resolution economized into a single call). Labels are deduped
    case-insensitively (first spelling wins). A missing/failed resolution, or an
    entity with no type statements, yields no concepts rather than failing.
    """
    qids = _type_qids(entity)
    if not qids:
        return ()
    query = urlencode(
        {
            "action": "wbgetentities",
            "ids": "|".join(qids),
            "props": "labels",
            "languages": "|".join(_PREFERRED_LANGS),
            "format": "json",
        }
    )
    try:
        data = get_json(f"{SITE}/w/api.php?{query}")
    except Exception:  # the concept resolution is enrichment, never fatal
        return ()
    resolved = data.get("entities") if isinstance(data, dict) else None
    if not isinstance(resolved, dict):
        return ()
    seen: dict[str, str] = {}
    for qid in qids:  # keep the P31-before-P279 order the QIDs were collected in
        record = resolved.get(qid)
        name = _best_text(record.get("labels")) if isinstance(record, dict) else None
        if name:
            seen.setdefault(name.lower(), name)
    return tuple(seen.values())


def _type_qids(entity: dict[str, Any]) -> list[str]:
    """The deduped QID values of the entity's `P31`/`P279` statements, capped."""
    qids: list[str] = []
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return qids
    for prop in _TYPE_PROPERTIES:
        for value in _statement_values(claims.get(prop)):
            qid = value.get("id") if isinstance(value, dict) else None
            if isinstance(qid, str) and _QID.fullmatch(qid):
                qids.append(qid)
    return list(dict.fromkeys(qids))[:_MAX_TYPES]


def _links(entity: dict[str, Any]) -> tuple:
    """The entity's outbound edges: its English Wikipedia article, plus `P856` sites.

    The English Wikipedia sitelink becomes an `en.wikipedia.org/wiki/<Title>` URL —
    the Wikidata↔Wikipedia edge `scrolls related`/`graph` resolves to the saved
    Wikipedia scroll (the title's spaces become underscores, the canonical
    Wikipedia URL form the detector reads back). The official-website statement
    (`P856`) adds each declared site. Deduped, order preserved.
    """
    links: list[str] = []
    sitelinks = entity.get("sitelinks")
    enwiki = sitelinks.get("enwiki") if isinstance(sitelinks, dict) else None
    title = _clean(enwiki.get("title")) if isinstance(enwiki, dict) else None
    if title:
        links.append(f"{ENWIKI}/{quote(title.replace(' ', '_'))}")
    claims = entity.get("claims")
    if isinstance(claims, dict):
        for value in _statement_values(claims.get("P856")):
            url = _clean(value) if isinstance(value, str) else None
            if url:
                links.append(url)
    return tuple(dict.fromkeys(links))


def _media(entity: dict[str, Any]) -> tuple:
    """The representative image (`P18`) as a single `thumbnail` media ref, else ().

    `P18` is a Wikimedia Commons filename; the first one becomes a `thumbnail` (the
    Open Library cover convention, ADR 0073/0011) served by Commons' `Special:
    FilePath` route at a bounded width — an absolute URL the capture step localizes.
    """
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return ()
    for value in _statement_values(claims.get("P18")):
        filename = _clean(value) if isinstance(value, str) else None
        if filename:
            url = f"{COMMONS}/{quote(filename)}?width=640"
            return ({"type": "thumbnail", "url": url},)
    return ()


def _statement_values(claims: Any) -> list[Any]:
    """The mainsnak datavalues of a property's statements (only real `value` snaks).

    A statement may be `somevalue`/`novalue` (an asserted unknown/none), which
    carries no datavalue and is skipped, so only concrete values are returned.
    """
    values: list[Any] = []
    if not isinstance(claims, list):
        return values
    for claim in claims:
        snak = claim.get("mainsnak") if isinstance(claim, dict) else None
        if not isinstance(snak, dict) or snak.get("snaktype") != "value":
            continue
        datavalue = snak.get("datavalue")
        if isinstance(datavalue, dict) and "value" in datavalue:
            values.append(datavalue["value"])
    return values


def _projection(entity: dict[str, Any], canonical_id: str) -> dict[str, Any]:
    """The slim record kept in `raw_text` — what the adapter consumed, not the whole.

    A Wikidata entity can be hundreds of KB (every language's label, hundreds of
    sitelinks); storing it whole would bloat the index. The projection keeps the
    en/`mul` labels and descriptions, the four claim properties the adapter reads,
    and the English sitelink — enough to rebuild the scroll's structured fields.
    """
    labels = entity.get("labels") if isinstance(entity.get("labels"), dict) else {}
    descriptions = (
        entity.get("descriptions") if isinstance(entity.get("descriptions"), dict) else {}
    )
    claims = entity.get("claims") if isinstance(entity.get("claims"), dict) else {}
    sitelinks = entity.get("sitelinks") if isinstance(entity.get("sitelinks"), dict) else {}
    kept_props = (*_TYPE_PROPERTIES, "P18", "P856")
    return {
        "id": canonical_id,
        "type": entity.get("type"),
        "labels": {k: labels[k] for k in _PREFERRED_LANGS if k in labels},
        "descriptions": {k: descriptions[k] for k in _PREFERRED_LANGS if k in descriptions},
        "claims": {p: claims[p] for p in kept_props if p in claims},
        "sitelinks": {k: sitelinks[k] for k in ("enwiki",) if k in sitelinks},
    }


def _clean(value: Any) -> str | None:
    """A non-empty trimmed string, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


_get_json = http.get_json
