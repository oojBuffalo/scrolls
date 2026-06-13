"""PubMed fetch adapter (IDEAS.md §6, ADR 0065).

One GET against NCBI's keyless E-utilities efetch endpoint returns a
PubMed article record as XML, parsed with stdlib ElementTree — no auth,
no runtime dependency, the arXiv adapter's discipline (ADR 0008). PubMed
is the biomedical-literature sibling of the arXiv (preprints) and Crossref
(published works carrying a DOI) adapters: the largest index of life-
sciences papers, keyed by an integer PMID.

Three facts shape the design:

1. **MeSH descriptors are the concepts.** PubMed tags each indexed record
   with Medical Subject Headings — a curated controlled vocabulary
   (`Protein Folding`, `DNA Cleavage`) — the highest-signal concept source
   any adapter has, the role arXiv's taxonomy names and github topics fill
   (ADR 0012, ADR 0007). Records not yet MEDLINE-indexed carry no MeSH, so
   author `Keyword`s are the fallback, keeping an ahead-of-print article a
   citizen of the concept graph rather than an island.

2. **The abstract is the content; there is no full text.** PubMed holds
   metadata and abstracts, not full text (that is PubMed Central), so the
   abstract — the `AbstractText` sections joined with their structured
   labels — is the searchable `summary`, with no `extracted_text`. This
   mirrors Crossref exactly (ADR 0037); a record with no abstract degrades
   to a metadata-only scroll (ADR 0002).

3. **The DOI is the one outgoing link.** A PubMed record carries the
   article's DOI; the resulting `https://doi.org/<doi>` link resolves
   (through source detection in `related`/`graph`) to the `crossref:<doi>`
   item a saved DOI mints, wiring the PubMed record to its published
   Crossref scroll — the biomedical analog of arXiv's preprint↔published
   edge (ADR 0038).

The publication date follows a precedence — the electronic `ArticleDate`
first (clean numeric Y/M/D), then the journal issue `PubDate` (which may
carry a month name or only a year), then the PubMed history — so a record
dates the scroll however it carries its date (ADR 0024). Publication types
and the journal title become `tags`, the controlled-facet slot Crossref's
`type`/venue fill; and a PubMed record classifies as `paper` like an arXiv
or Crossref one (ADR 0004). The raw efetch XML is kept in `raw_text` so the
scroll can be rebuilt without refetching.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlencode
from xml.etree import ElementTree

from scrolls.dates import to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import http

API_ROOT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov"
DOI_RESOLVER = "https://doi.org"

# Some biomedical papers carry hundreds of authors; `author` is a display
# string, so a long list keeps a readable head and appends "et al." — the
# Crossref rule (ADR 0037).
_MAX_AUTHORS = 10

GetText = Callable[[str], str]

_MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}


def fetch_item(item: ScrollItem, *, get_text: GetText | None = None) -> ScrollItem:
    """Fetch a detected PubMed record's metadata and abstract; return it 'fetched'.

    Raises FetchError when the PMID is missing, the request fails, the
    response does not parse, or it carries no article (an unknown PMID
    returns an empty set). Abstract/MeSH/DOI absences never raise — the
    scroll degrades gracefully. The input item is never mutated.
    """
    get_text = get_text or _get_text
    if not item.source_id:
        raise FetchError(f"cannot determine PMID for item {item.id!r}")

    url = f"{API_ROOT}?{urlencode({'db': 'pubmed', 'id': item.source_id, 'retmode': 'xml'})}"
    try:
        xml_text = get_text(url)
        root = ElementTree.fromstring(xml_text)
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        raise FetchError(f"PubMed efetch request failed: {exc}") from exc

    article = root.find("PubmedArticle")
    citation = article.find("MedlineCitation") if article is not None else None
    art = citation.find("Article") if citation is not None else None
    if article is None or citation is None or art is None:
        raise FetchError(f"PubMed article not found: {item.source_id}")

    pmid = _text(citation.find("PMID")) or item.source_id
    summary = _abstract(art)
    hashed = summary or xml_text
    return replace(
        item,
        # the article title, then any seeded (e.g. feed) title, then the PMID as
        # a last resort so the scroll is never untitled — Crossref's DOI fallback
        title=_title(art) or item.title or pmid,
        author=_authors(art),
        published_at=_published(art, article) or item.published_at,
        canonical_url=f"{ARTICLE_URL}/{pmid}/",
        raw_text=xml_text,
        summary=summary,
        tags=_tags(art),
        concepts=_concepts(citation),
        links=_doi_links(article, art),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "pubmed",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": "pubmed-efetch:xml",
        },
        stage="fetched",
    )


def _text(element: ElementTree.Element | None) -> str | None:
    """An element's full text content, whitespace collapsed, or None.

    `itertext()` gathers text across inline markup PubMed titles and abstracts
    carry (`<i>`, `<sup>`, `<sub>`), so `the <i>S. pyogenes</i> system` reads
    `the S. pyogenes system`. Numeric/named entities are already decoded by the
    parser. Returns None for a missing element or empty text.
    """
    if element is None:
        return None
    text = " ".join("".join(element.itertext()).split())
    return text or None


def _title(art: ElementTree.Element) -> str | None:
    """The article title, falling back to the vernacular (original-language) one."""
    return _text(art.find("ArticleTitle")) or _text(art.find("VernacularTitle"))


def _authors(art: ElementTree.Element) -> str | None:
    """The author list as a display string, truncated past `_MAX_AUTHORS`.

    Each `Author` is `LastName`+`ForeName` for a person (rendered "Fore Last",
    the Crossref "Given Family" order) or a `CollectiveName` for a group/
    consortium. A list longer than the cap keeps its head and appends "et al."
    so a 1000-author genomics paper does not produce a 1000-name field.
    """
    author_list = art.find("AuthorList")
    if author_list is None:
        return None
    names = [
        name
        for name in (_format_author(a) for a in author_list.findall("Author"))
        if name
    ]
    if not names:
        return None
    if len(names) > _MAX_AUTHORS:
        names = names[:_MAX_AUTHORS] + ["et al."]
    return ", ".join(names)


def _format_author(author: ElementTree.Element) -> str | None:
    """One author as "Fore Last", the bare last/fore name, or a collective name."""
    collective = _text(author.find("CollectiveName"))
    if collective:
        return collective
    last = _text(author.find("LastName"))
    fore = _text(author.find("ForeName")) or _text(author.find("Initials"))
    if last and fore:
        return f"{fore} {last}"
    return last or fore


def _abstract(art: ElementTree.Element) -> str | None:
    """The abstract reduced to plain text, structured sections kept, or None.

    A structured abstract has several `AbstractText` elements with `Label`
    attributes (BACKGROUND, METHODS, RESULTS, …); each labelled section is
    prefixed `LABEL: …` and sections are joined with a space so the whole
    abstract stays one searchable `summary` field, the Crossref shape. A record
    with no abstract returns None (the metadata-only scroll, ADR 0002).
    """
    abstract = art.find("Abstract")
    if abstract is None:
        return None
    parts = []
    for node in abstract.findall("AbstractText"):
        text = _text(node)
        if not text:
            continue
        label = (node.get("Label") or "").strip()
        parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts) or None


def _tags(art: ElementTree.Element) -> tuple[str, ...]:
    """Publication types and the journal title as deduped tags.

    `PublicationType` is a controlled vocabulary (`Journal Article`, `Review`,
    `Meta-Analysis`, `Randomized Controlled Trial`) — the structured facet
    Crossref's `type` fills — and the journal `Title` is the venue that lets
    `scrolls related` corroborate two papers from the same journal, exactly as
    the Crossref adapter tags `type` + `container-title` (ADR 0037).
    """
    types = [_text(pt) for pt in art.findall("PublicationTypeList/PublicationType")]
    venue = _text(art.find("Journal/Title"))
    return _dedupe([*types, venue])


def _concepts(citation: ElementTree.Element) -> tuple[str, ...]:
    """MeSH descriptor names as concepts, falling back to author keywords.

    MeSH (`MeshHeadingList/MeshHeading/DescriptorName`) is PubMed's curated
    controlled vocabulary — the highest-signal concept source, joining github
    topics and arXiv taxonomy names in the KB concept graph (ADR 0007, ADR 0012).
    A record not yet MEDLINE-indexed (an ahead-of-print article) carries no MeSH
    but often does carry author `Keyword`s, used as the fallback so the article
    still joins the graph rather than becoming an island.
    """
    mesh = _dedupe(
        _text(d) for d in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")
    )
    if mesh:
        return mesh
    return _dedupe(_text(k) for k in citation.findall("KeywordList/Keyword"))


def _doi_links(
    article: ElementTree.Element, art: ElementTree.Element
) -> tuple[str, ...]:
    """The article's DOI(s) as `doi.org` links, deduped, or empty.

    The DOI lives in `PubmedData/ArticleIdList/ArticleId[@IdType='doi']` and,
    for some records, in `Article/ELocationID[@EIdType='doi']`; both are
    gathered and the resulting `https://doi.org/<doi>` link resolves (through
    source detection) to the `crossref:<doi>` item a saved DOI mints — the
    PubMed↔Crossref paper edge (ADR 0038's arXiv analog). A record with no DOI
    (older or non-journal entries) is honestly empty. The PMC full-text id is
    deliberately not turned into a link: PMC is not a detected source, so it
    would resolve to no saved item.
    """
    dois = [
        _text(aid)
        for aid in article.findall("PubmedData/ArticleIdList/ArticleId")
        if aid.get("IdType") == "doi"
    ]
    dois += [
        _text(eloc)
        for eloc in art.findall("ELocationID")
        if eloc.get("EIdType") == "doi"
    ]
    return tuple(dict.fromkeys(f"{DOI_RESOLVER}/{doi}" for doi in dois if doi))


def _published(art: ElementTree.Element, article: ElementTree.Element) -> str | None:
    """The publication date as UTC ISO 8601, by PubMed's date precedence.

    `ArticleDate` (DateType="Electronic") is the clean numeric date of first
    online publication and is preferred; the journal issue `PubDate` is next
    (it may carry a month name like `Aug`, only a year, or a free-text
    `MedlineDate`); the PubMed history `pubmed` status date is the final
    fallback. A partial date pads missing month/day to the start of the period
    — invented precision, but one uniform shape (ADR 0024).
    """
    for adate in art.findall("ArticleDate"):
        iso = _date_from(adate)
        if iso:
            return iso
    iso = _date_from(art.find("Journal/JournalIssue/PubDate"))
    if iso:
        return iso
    for hist in article.findall("PubmedData/History/PubMedPubDate"):
        if hist.get("PubStatus") == "pubmed":
            iso = _date_from(hist)
            if iso:
                return iso
    return None


def _date_from(element: ElementTree.Element | None) -> str | None:
    """A PubMed date element (Year/Month/Day or a free-text MedlineDate) as UTC ISO.

    Month may be numeric (`6`), a three-letter English abbreviation (`Jun`), or
    a full name; an unrecognized month or day falls back to the start of the
    period rather than dropping the whole date. A `MedlineDate` (free text like
    `2012 Jul-Aug`) contributes its leading four-digit year.
    """
    if element is None:
        return None
    year = _text(element.find("Year"))
    if year and year.isdigit():
        month = _month_number(_text(element.find("Month")))
        day_text = _text(element.find("Day"))
        day = int(day_text) if day_text and day_text.isdigit() else 1
        # try full date, then first-of-month, then first-of-year so an out-of-
        # range day (rare, but present in the wild) still dates the scroll
        for candidate in (
            f"{int(year):04d}-{month:02d}-{day:02d}",
            f"{int(year):04d}-{month:02d}-01",
            f"{int(year):04d}-01-01",
        ):
            iso = to_utc_iso(candidate)
            if iso:
                return iso
        return None
    medline = _text(element.find("MedlineDate"))
    if medline:
        match = re.search(r"\d{4}", medline)
        if match:
            return to_utc_iso(f"{match.group()}-01-01")
    return None


def _month_number(text: str | None) -> int:
    """A PubMed month (numeric, `Jun`, or a full name) as 1–12, defaulting to 1."""
    if not text:
        return 1
    cleaned = text.strip().lower()
    if cleaned.isdigit():
        number = int(cleaned)
        return number if 1 <= number <= 12 else 1
    return _MONTHS.get(cleaned[:3], 1)


def _dedupe(values) -> tuple[str, ...]:
    """Non-empty strings, order-preserving and deduped."""
    return tuple(dict.fromkeys(value for value in values if value))


_get_text = http.get_text
