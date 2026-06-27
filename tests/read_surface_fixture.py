"""A wide read-surface fixture shared by the determinism contracts.

`seed_read_surface_determinism_mix(paths)` builds one library where every
order-sensitive read fold — MCP *and* CLI — is non-vacuous, so the
byte-identity claims in `test_mcp.py` (H388, the whole MCP read-surface
determinism contract) and `test_cli.py` (H394, the CLI read-surface
determinism contract) are real (an all-empty payload passes a mis-ordered
fold too). It is the pure DB seeder only: each surface keeps its own
`_prepare_*`/`_assert_*_non_vacuous` helpers (the MCP payload shapes and the
CLI JSON/markdown shapes diverge), but both seed from this single source of
truth — the roadmap H394 "reuse `_seed_read_surface_determinism_mix`" directive
and the `pdf_fixtures` shared-helper precedent.
"""

import dataclasses
import sqlite3

from scrolls.custody import CustodyEvent, conflict_event, record_events
from scrolls.items import ScrollItem, adopt_incoming, insert_item
from scrolls.render import write_scroll


def seed_read_surface_determinism_mix(paths):
    """One wide library where every order-sensitive read fold is non-vacuous.

    A single fixture that drives the *whole* read surface, so the byte-identity
    claims are real (an all-empty payload passes a mis-ordered fold too):

    - **four sources** (arxiv, crossref, web, x) → a multi-key `by_source` map
      on `get_library_health`/`get_link_graph`/`list_sources`;
    - **three DOI-clustered works** (`get_works`): two with a full preprint + a
      reference DOI record, and a third all-reference work so `works.most_at_risk`
      is non-null;
    - **link edges** (`web:hub`, `arxiv:dbb`, `crossref:dba` all link to
      `arxiv:dba`'s URL) → a ≥3-node, ≥2-edge graph;
    - a **"Database" concept** with ≥3 members and an **"efficient" tag** with ≥3
      members → multi-element `get_concept_page`/`get_tag_page` renders;
    - a **byte-identical content pair** → `content_duplicates.groups`;
    - a **drifted** item carrying an unresolved **conflict** → `drift.events` +
      `conflicts.events` + a non-empty `get_scroll_history`;
    - a **tampered archived prior** → `archive.events` + `list_archived`/
      `get_archived` recovery reads.
    """
    db = paths.db_path

    def _item(ident, source, **overrides):
        sid = ident.split(":", 1)[1]
        fields = dict(
            id=ident, source=source, source_id=sid,
            url=f"https://{source}.example/{sid}",
            saved_at="2026-06-12T08:00:00+00:00", stage="rendered",
        )
        fields.update(overrides)
        return ScrollItem(**fields)

    def _render(item):
        # a rendered scroll file (markdown_path set) so the KB compiler folds it
        # into the concept/tag pages get_concept_page/get_tag_page read
        insert_item(db, write_scroll(paths, item))

    # --- three DOI-clustered works (get_works) -------------------------------
    # work A: a full preprint (the link-graph hub target, a Database/Indexing member)
    #         + a reference DOI record
    _render(_item(
        "arxiv:dba", "arxiv", title="Indexing in a database",
        raw_text="A database index keeps lookups fast.",
        extracted_text="A database index keeps lookups fast.",
        content_hash="sha256:dba", concepts=("Database", "Indexing"),
        tags=("efficient",), links=("https://doi.org/10.1000/db",)))
    insert_item(db, _item(
        "crossref:dba", "crossref",
        links=("https://doi.org/10.1000/db", "https://arxiv.example/dba")))
    # work B: a second full preprint (a Database member) + reference DOI record
    _render(_item(
        "arxiv:dbb", "arxiv", title="A database query engine",
        raw_text="A database query engine plans joins.",
        extracted_text="A database query engine plans joins.",
        content_hash="sha256:dbb", concepts=("Database",), tags=("efficient",),
        links=("https://doi.org/10.2000/db", "https://arxiv.example/dba")))
    insert_item(db, _item(
        "crossref:dbb", "crossref", links=("https://doi.org/10.2000/db",)))
    # work C: two reference reps of one DOI → an all-reference at-risk work
    insert_item(db, _item("arxiv:ref1", "arxiv", links=("https://doi.org/10.3000/db",)))
    insert_item(db, _item("crossref:ref2", "crossref", links=("https://doi.org/10.3000/db",)))

    # --- a web hub: a rendered search/concept/tag member that links into the graph
    _render(_item(
        "web:hub", "web", title="Database hub overview",
        raw_text="An overview of database tools.",
        extracted_text="An overview of database tools and indexing.",
        content_hash="sha256:hub", concepts=("Database", "Indexing"),
        tags=("efficient",), links=("https://arxiv.example/dba",)))
    # an x thread → a 4th source and a cross-source search hit
    insert_item(db, _item(
        "x:post", "x", title="A database thread",
        raw_text="A thread about database internals.",
        extracted_text="A thread about database internals.",
        content_hash="sha256:xp"))

    # --- a byte-identical content-duplicate pair (content_duplicates) ---------
    for ident in ("web:dup1", "web:dup2"):
        insert_item(db, _item(
            ident, "web", title="A duplicated note",
            extracted_text="same body", content_hash="sha256:dup", stage="fetched"))

    # --- a drifted item that also carries an unresolved conflict -------------
    record_events(db, [
        CustodyEvent(item_id="web:hub", checked_at="2026-06-14T00:00:00+00:00",
                     status="drifted", prior_hash="sha256:hub",
                     observed_hash="sha256:moved"),
        conflict_event("web:hub", held_hash="sha256:hub",
                       incoming_hash="sha256:incoming",
                       now="2026-06-15T00:00:00+00:00"),
    ])

    # --- a tampered archived prior (the archive.events integrity alarm, plus the
    #     list_archived / get_archived recovery reads) ------------------------
    held = _item("web:archived", "web", title="An archived note",
                 extracted_text="the prior body", content_hash="sha256:held",
                 stage="fetched")
    insert_item(db, held)
    adopt_incoming(db, dataclasses.replace(
        held, extracted_text="a later capture", content_hash="sha256:moved"),
        archived_at="2026-06-22T00:00:00+00:00")
    # tamper the recorded prior hash so doctor's archive integrity alarm fires —
    # the un-launderable recovery-mismatch row (the H381 health-mix precedent)
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
                     ("sha256:tampered", held.id))
    conn.close()
