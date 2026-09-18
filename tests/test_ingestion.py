import pytest

from ingestion.chunkers import MAX_CHUNK_WORDS, chunk_document, chunk_qa_pairs, chunk_words
from ingestion.loaders import parse_front_matter
from ingestion.metadata_tagger import make_chunk_id


def test_faq_keeps_multi_paragraph_answer_with_its_question():
    text = "Q: How to X?\nA: Step one.\n\nThen step two.\n\nQ: Next?\nA: yes"
    chunks = chunk_qa_pairs(text)
    assert chunks == ["Q: How to X?\nA: Step one.\n\nThen step two.", "Q: Next?\nA: yes"]


def test_chunk_ids_unique_even_with_shared_prefix():
    a = "Q: How do I cancel my subscription on the mobile app? A: ..."
    b = "Q: How do I cancel my subscription on the mobile app? A: different"
    assert a[:50] == b[:50]
    assert make_chunk_id("faq.md", 0, a) != make_chunk_id("faq.md", 1, b)
    assert make_chunk_id("faq.md", 0, a) != make_chunk_id("faq.md", 0, b)


def test_chunk_words_guards_overlap():
    with pytest.raises(ValueError):
        chunk_words("a b c", chunk_size=5, overlap=5)


def test_markdown_chunks_fit_embedder_window_and_carry_breadcrumb():
    body = "# Guide\n\n## Setup\n\n" + ("word " * 500) + "\n\n## Usage\n\nShort usage section."
    chunks = chunk_document(body, "product_info", title="Guide")
    assert all(len(c.split("\n", 1)[1].split()) <= MAX_CHUNK_WORDS for c in chunks)
    assert chunks[0].startswith("Guide > Setup\n")
    assert chunks[-1].startswith("Guide > Usage\n")


def test_front_matter_parsing():
    meta, body = parse_front_matter("---\ntitle: T\ntenant_id: acme\n---\n# Body\n")
    assert meta == {"title": "T", "tenant_id": "acme"} and body == "# Body\n"
    assert parse_front_matter("no front matter") == ({}, "no front matter")
