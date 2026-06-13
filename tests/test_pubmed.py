"""Tests for the PubMed fetch adapter (IDEAS.md §6, ADR 0065).

The XML transport is faked with an efetch record recorded (and trimmed)
from the real E-utilities API for PMID 22745249 (Jinek et al., the
CRISPR-Cas9 Science paper, DOI 10.1126/science.1225829), so the field
mapping, MeSH-as-concepts, the abstract-as-summary semantics, the date
precedence, the DOI cross-source link, and error handling are all covered
offline (ADR 0001).
"""

import re

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.pubmed import fetch_item

# Recorded (and trimmed) from the E-utilities efetch response for PMID 22745249
# (Jinek et al. 2012, Science). The print issue PubDate carries a month *name*
# (Aug); the electronic ArticleDate is numeric and should win.
ARTICLE_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">22745249</PMID>
    <Article PubModel="Print-Electronic">
      <Journal>
        <ISSN IssnType="Electronic">1095-9203</ISSN>
        <JournalIssue CitedMedium="Internet">
          <Volume>337</Volume>
          <Issue>6096</Issue>
          <PubDate>
            <Year>2012</Year>
            <Month>Aug</Month>
            <Day>17</Day>
          </PubDate>
        </JournalIssue>
        <Title>Science (New York, N.Y.)</Title>
        <ISOAbbreviation>Science</ISOAbbreviation>
      </Journal>
      <ArticleTitle>A programmable dual-RNA-guided DNA endonuclease in adaptive bacterial immunity.</ArticleTitle>
      <ELocationID EIdType="doi" ValidYN="Y">10.1126/science.1225829</ELocationID>
      <Abstract>
        <AbstractText>Clustered regularly interspaced short palindromic repeats (CRISPR)/CRISPR-associated (Cas) systems provide bacteria and archaea with adaptive immunity against viruses &amp; plasmids. We show that in the <i>Streptococcus pyogenes</i> system, Cas9 is a dual-RNA-guided DNA endonuclease.</AbstractText>
      </Abstract>
      <AuthorList CompleteYN="Y">
        <Author ValidYN="Y"><LastName>Jinek</LastName><ForeName>Martin</ForeName><Initials>M</Initials></Author>
        <Author ValidYN="Y"><LastName>Chylinski</LastName><ForeName>Krzysztof</ForeName><Initials>K</Initials></Author>
        <Author ValidYN="Y"><LastName>Fonfara</LastName><ForeName>Ines</ForeName><Initials>I</Initials></Author>
        <Author ValidYN="Y"><LastName>Hauer</LastName><ForeName>Michael</ForeName><Initials>M</Initials></Author>
        <Author ValidYN="Y"><LastName>Doudna</LastName><ForeName>Jennifer A</ForeName><Initials>JA</Initials></Author>
        <Author ValidYN="Y"><LastName>Charpentier</LastName><ForeName>Emmanuelle</ForeName><Initials>E</Initials></Author>
      </AuthorList>
      <Language>eng</Language>
      <PublicationTypeList>
        <PublicationType UI="D016428">Journal Article</PublicationType>
        <PublicationType UI="D013485">Research Support, Non-U.S. Gov't</PublicationType>
      </PublicationTypeList>
      <ArticleDate DateType="Electronic">
        <Year>2012</Year>
        <Month>06</Month>
        <Day>28</Day>
      </ArticleDate>
    </Article>
    <MeshHeadingList>
      <MeshHeading><DescriptorName UI="D001435" MajorTopicYN="N">Bacteriophages</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D001483" MajorTopicYN="N">Base Sequence</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D053837" MajorTopicYN="N">DNA Breaks, Double-Stranded</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D021341" MajorTopicYN="Y">DNA Cleavage</DescriptorName><QualifierName UI="Q000302">isolation &amp; purification</QualifierName></MeshHeading>
      <MeshHeading><DescriptorName UI="D015254" MajorTopicYN="N">Deoxyribonucleases, Type II Site-Specific</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D018887" MajorTopicYN="N">Inverted Repeat Sequences</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D008969" MajorTopicYN="N">Molecular Sequence Data</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D009683" MajorTopicYN="N">Nucleic Acid Conformation</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D010957" MajorTopicYN="N">Plasmids</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D012313" MajorTopicYN="Y">RNA</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D013356" MajorTopicYN="N">Streptococcus pyogenes</DescriptorName></MeshHeading>
    </MeshHeadingList>
  </MedlineCitation>
  <PubmedData>
    <History>
      <PubMedPubDate PubStatus="entrez"><Year>2012</Year><Month>6</Month><Day>29</Day></PubMedPubDate>
      <PubMedPubDate PubStatus="pubmed"><Year>2012</Year><Month>6</Month><Day>29</Day></PubMedPubDate>
      <PubMedPubDate PubStatus="medline"><Year>2012</Year><Month>9</Month><Day>5</Day></PubMedPubDate>
    </History>
    <PublicationStatus>ppublish</PublicationStatus>
    <ArticleIdList>
      <ArticleId IdType="pubmed">22745249</ArticleId>
      <ArticleId IdType="doi">10.1126/science.1225829</ArticleId>
      <ArticleId IdType="pmc">PMC6286148</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>"""

EMPTY_SET = '<?xml version="1.0" ?>\n<PubmedArticleSet>\n</PubmedArticleSet>'


def make_item(**overrides):
    base = dict(
        id="pubmed:22745249",
        source="pubmed",
        source_id="22745249",
        url="https://pubmed.ncbi.nlm.nih.gov/22745249/",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fetch(xml=ARTICLE_XML, item=None):
    return fetch_item(item or make_item(), get_text=lambda url: xml)


def drop(*blocks, xml=ARTICLE_XML):
    """The fixture XML with whole `<Tag>…</Tag>` blocks removed (DOTALL)."""
    for tag in blocks:
        xml = re.sub(rf"<{tag}\b.*?</{tag}>", "", xml, flags=re.DOTALL)
    return xml


def test_fetch_maps_core_metadata():
    fetched = fetch()

    # the title is kept verbatim (trailing period and all), whitespace collapsed
    assert fetched.title == (
        "A programmable dual-RNA-guided DNA endonuclease in adaptive bacterial immunity."
    )
    # authors render "Fore Last", the Crossref "Given Family" order
    assert fetched.author == (
        "Martin Jinek, Krzysztof Chylinski, Ines Fonfara, "
        "Michael Hauer, Jennifer A Doudna, Emmanuelle Charpentier"
    )
    assert fetched.canonical_url == "https://pubmed.ncbi.nlm.nih.gov/22745249/"
    assert fetched.provenance["adapter"] == "pubmed"
    assert fetched.provenance["extraction_method"] == "pubmed-efetch:xml"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_abstract_becomes_plain_summary_no_full_text():
    fetched = fetch()
    summary = fetched.summary
    assert summary.startswith("Clustered regularly interspaced")
    # entities are decoded by the parser
    assert "viruses & plasmids" in summary
    # inline <i> markup is unwrapped, whitespace collapsed
    assert "the Streptococcus pyogenes system" in summary
    # PubMed has no full text (that is PMC), so no extracted_text — like Crossref
    assert fetched.extracted_text is None


def test_structured_abstract_keeps_section_labels():
    xml = ARTICLE_XML.replace(
        "<AbstractText>Clustered",
        '<AbstractText Label="BACKGROUND">Clustered',
    ).replace(
        "DNA endonuclease.</AbstractText>",
        'DNA endonuclease.</AbstractText>'
        '<AbstractText Label="RESULTS">Cas9 can be programmed.</AbstractText>',
    )
    summary = fetch(xml).summary
    assert summary.startswith("BACKGROUND: Clustered")
    assert "RESULTS: Cas9 can be programmed." in summary


def test_mesh_descriptors_become_concepts():
    # the curated MeSH vocabulary, descriptor names only (qualifiers dropped)
    assert fetch().concepts == (
        "Bacteriophages",
        "Base Sequence",
        "DNA Breaks, Double-Stranded",
        "DNA Cleavage",
        "Deoxyribonucleases, Type II Site-Specific",
        "Inverted Repeat Sequences",
        "Molecular Sequence Data",
        "Nucleic Acid Conformation",
        "Plasmids",
        "RNA",
        "Streptococcus pyogenes",
    )


def test_author_keywords_are_the_concept_fallback_without_mesh():
    # an ahead-of-print record (no MeSH yet) still joins the concept graph;
    # KeywordList is a sibling of MeshHeadingList under MedlineCitation
    xml = re.sub(
        r"<MeshHeadingList\b.*?</MeshHeadingList>",
        '<KeywordList Owner="NOTNLM">'
        '<Keyword MajorTopicYN="Y">CRISPR-Cas9</Keyword>'
        '<Keyword MajorTopicYN="N">genome editing</Keyword>'
        "</KeywordList>",
        ARTICLE_XML,
        flags=re.DOTALL,
    )
    assert fetch(xml).concepts == ("CRISPR-Cas9", "genome editing")


def test_no_mesh_no_keywords_is_honestly_empty():
    assert fetch(drop("MeshHeadingList")).concepts == ()


def test_publication_types_and_journal_become_tags():
    assert fetch().tags == (
        "Journal Article",
        "Research Support, Non-U.S. Gov't",
        "Science (New York, N.Y.)",
    )


def test_doi_becomes_the_cross_source_link():
    # the doi.org link resolves (through detection) to the crossref:<doi> item,
    # the PubMed↔Crossref paper edge (ADR 0038's biomedical analog)
    assert fetch().links == ("https://doi.org/10.1126/science.1225829",)


def test_no_doi_leaves_links_empty():
    assert fetch(drop("ELocationID", "ArticleIdList")).links == ()


def test_published_at_prefers_electronic_article_date():
    # the numeric ArticleDate (2012-06-28) wins over the name-month PubDate
    assert fetch().published_at == "2012-06-28T00:00:00+00:00"


def test_published_at_falls_back_to_journal_pubdate_with_month_name():
    # without ArticleDate, the issue PubDate's month *name* is parsed
    assert fetch(drop("ArticleDate")).published_at == "2012-08-17T00:00:00+00:00"


def test_year_only_pubdate_pads_to_first_of_year():
    xml = drop("ArticleDate").replace(
        "<Month>Aug</Month>\n            <Day>17</Day>\n          ", ""
    )
    assert fetch(xml).published_at == "2012-01-01T00:00:00+00:00"


def test_medline_date_contributes_its_year():
    xml = drop("ArticleDate").replace(
        "<Year>2012</Year>\n            <Month>Aug</Month>\n            <Day>17</Day>",
        "<MedlineDate>2012 Jul-Aug</MedlineDate>",
    )
    assert fetch(xml).published_at == "2012-01-01T00:00:00+00:00"


def test_published_at_falls_back_to_pubmed_history():
    # neither ArticleDate nor a parseable PubDate: the history 'pubmed' status
    xml = drop("ArticleDate").replace(
        "<Year>2012</Year>\n            <Month>Aug</Month>\n            <Day>17</Day>",
        "",
    )
    assert fetch(xml).published_at == "2012-06-29T00:00:00+00:00"


def test_long_author_list_truncated_with_et_al():
    authors = "".join(
        f"<Author ValidYN='Y'><LastName>B{i}</LastName>"
        f"<ForeName>A{i}</ForeName></Author>"
        for i in range(25)
    )
    xml = re.sub(
        r"<AuthorList\b.*?</AuthorList>",
        f"<AuthorList CompleteYN='Y'>{authors}</AuthorList>",
        ARTICLE_XML,
        flags=re.DOTALL,
    )
    author = fetch(xml).author
    assert author.endswith(", et al.")
    assert author.count(",") == 10  # 10 names + the trailing "et al." marker


def test_collective_author_name_is_used():
    xml = re.sub(
        r"<AuthorList\b.*?</AuthorList>",
        "<AuthorList CompleteYN='N'><Author ValidYN='Y'>"
        "<CollectiveName>CRISPR Consortium</CollectiveName></Author></AuthorList>",
        ARTICLE_XML,
        flags=re.DOTALL,
    )
    assert fetch(xml).author == "CRISPR Consortium"


def test_missing_authors_leaves_author_absent():
    assert fetch(drop("AuthorList")).author is None


def test_no_abstract_degrades_to_metadata_only():
    fetched = fetch(drop("Abstract"))
    assert fetched.summary is None
    # still a useful scroll: title, authors, journal, date, MeSH
    assert fetched.title.startswith("A programmable")
    assert fetched.concepts[0] == "Bacteriophages"


def test_title_falls_back_to_pmid_when_absent():
    fetched = fetch(drop("ArticleTitle", "VernacularTitle"))
    assert fetched.title == "22745249"


def test_keeps_raw_efetch_xml():
    assert "<PMID Version=\"1\">22745249</PMID>" in fetch().raw_text


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://www.ncbi.nlm.nih.gov/pubmed/22745249")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_requests_the_expected_efetch_url():
    seen = []

    def get_text(url):
        seen.append(url)
        return ARTICLE_XML

    fetch_item(make_item(), get_text=get_text)
    assert seen == [
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        "?db=pubmed&id=22745249&retmode=xml"
    ]


@pytest.mark.parametrize("source_id", [None, ""])
def test_requires_a_pmid(source_id):
    item = make_item(id="pubmed:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine PMID"):
        fetch_item(item, get_text=lambda url: ARTICLE_XML)


def test_unknown_pmid_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_text=lambda url: EMPTY_SET)


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 400: Bad Request")

    with pytest.raises(FetchError, match="400"):
        fetch_item(make_item(), get_text=boom)


def test_registered_in_fetch_adapters():
    assert FETCH_ADAPTERS["pubmed"] is fetch_item
