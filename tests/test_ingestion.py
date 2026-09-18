import json

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


# ------------------------------------------------------------------ file formats in data/

def _tiny_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of text per page (no PDF library needed)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.fixture
def mixed_data(tmp_path):
    sales = tmp_path / "sales_info"
    faq = tmp_path / "public_faq"
    sales.mkdir(), faq.mkdir()
    (sales / "notes.md").write_text("# Pricing notes\n\nPro costs $49.")
    (sales / "plain.txt").write_text("---\ntitle: Plain notes\n---\nVolume discounts start at 50 seats.")
    (sales / "prices.csv").write_text("plan;price;seats\nStarter;$9;1\nPro;$49;\n")
    (sales / "regions.tsv").write_text("region\towner\nEMEA\tDana\n")
    (sales / "deal.json").write_text(json.dumps({"customer": "Acme", "terms": {"discount": "15%"},
                                                 "products": ["Pro", "Add-on"]}))
    (sales / "log.jsonl").write_text('{"event": "renewal", "month": "May"}\nnot json\n{"event": "upsell"}\n')
    (sales / "brochure.pdf").write_bytes(_tiny_pdf(["Enterprise includes SSO", "Support is 24/7"]))
    (sales / "brochure.pdf.meta.yaml").write_text("title: Enterprise brochure\nclearance_level: 4\n")
    (sales / "scan.pdf").write_bytes(_tiny_pdf([""]))
    (sales / "contract.docx").write_bytes(b"PK\x03\x04")          # corrupt: skipped, build continues
    (sales / "deck.pptx").write_bytes(b"PK\x03\x04")
    (sales / ".hidden.md").write_text("secret")
    (faq / "faq.json").write_text(json.dumps([{"Question": "How do I reset?", "Answer": "Use Settings."},
                                              {"question": "Refunds?", "answer": "Within 30 days.", "tag": "billing"}]))
    return tmp_path


def test_every_supported_format_is_loaded(mixed_data):
    from ingestion.loaders import load_documents
    skipped = []
    docs = {d["source_doc_id"]: d for d in load_documents(mixed_data, skipped)}
    assert set(docs) == {"public_faq/faq.json", "sales_info/notes.md", "sales_info/plain.txt",
                         "sales_info/prices.csv", "sales_info/regions.tsv", "sales_info/deal.json",
                         "sales_info/log.jsonl", "sales_info/brochure.pdf"}
    reasons = dict(skipped)
    assert reasons.pop("sales_info/contract.docx").startswith("PackageNotFoundError")
    assert reasons == {"sales_info/scan.pdf": "UnreadableDocument: no text layer (scanned PDF? it would need OCR)",
                       "sales_info/deck.pptx": "unsupported type .pptx (save it as .pdf)"}
    assert docs["sales_info/prices.csv"]["text"] == "plan: Starter\nprice: $9\nseats: 1\n\nplan: Pro\nprice: $49"
    assert docs["sales_info/regions.tsv"]["text"] == "region: EMEA\nowner: Dana"
    assert docs["sales_info/deal.json"]["text"] == "customer: Acme\nterms.discount: 15%\nproducts: Pro, Add-on"
    assert docs["sales_info/log.jsonl"]["text"] == "event: renewal\nmonth: May\n\nevent: upsell"
    pdf = docs["sales_info/brochure.pdf"]
    assert "## Page 1\n\nEnterprise includes SSO" in pdf["text"] and "## Page 2\n\nSupport is 24/7" in pdf["text"]
    assert (pdf["title"], pdf["clearance_override"]) == ("Enterprise brochure", 4)   # from the sidecar
    assert docs["sales_info/plain.txt"]["title"] == "Plain notes"
    assert docs["public_faq/faq.json"]["text"] == ("Q: How do I reset?\nA: Use Settings.\n\n"
                                                   "Q: Refunds?\nA: Within 30 days.\ntag: billing")


def test_mixed_formats_chunk_and_tag(mixed_data):
    from ingestion.build_kb4 import collect_chunks
    chunks = collect_chunks(mixed_data)
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c["source_doc_id"], []).append(c)
    faq = [c["chunk_text"] for c in by_doc["public_faq/faq.json"]]
    assert faq == ["Faq\nQ: How do I reset?\nA: Use Settings.", "Faq\nQ: Refunds?\nA: Within 30 days.\ntag: billing"]
    pdf = by_doc["sales_info/brochure.pdf"]
    assert [c["chunk_text"].split("\n")[0] for c in pdf] == ["Enterprise brochure > Page 1", "Enterprise brochure > Page 2"]
    assert all(c["clearance_level"] == 4 for c in pdf)          # sidecar raised it above sales_info's 3


def test_oversized_faq_record_is_split():
    chunks = chunk_qa_pairs("title: long\nbody: " + "word " * 400)
    assert len(chunks) > 1 and all(len(c.split()) <= MAX_CHUNK_WORDS for c in chunks)


def test_word_documents(tmp_path):
    docx = pytest.importorskip("docx")
    from ingestion.loaders import load_documents
    folder = tmp_path / "company_info"
    folder.mkdir()
    d = docx.Document()
    d.core_properties.title = "Employee handbook"
    d.add_heading("Leave", level=1)
    d.add_paragraph("Staff get 25 days of paid leave.")
    d.add_paragraph("Carry over up to 5 days", style="List Bullet")
    table = d.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("Level", "Days"), ("Junior", "25"), ("Senior", "30")]):
        table.cell(r, 0).text, table.cell(r, 1).text = a, b
    d.add_heading("Remote work", level=1)
    d.add_paragraph("Two days a week.")
    d.save(folder / "handbook.docx")
    (folder / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    skipped = []
    [doc] = load_documents(tmp_path, skipped)
    assert doc["title"] == "Employee handbook"
    assert doc["text"] == ("## Leave\n\nStaff get 25 days of paid leave.\n\n- Carry over up to 5 days\n\n"
                           "Level: Junior\nDays: 25\n\nLevel: Senior\nDays: 30\n\n## Remote work\n\nTwo days a week.")
    assert skipped == [("company_info/old.doc", "unsupported type .doc (save it as .docx)")]


def test_excel_workbooks(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    import datetime

    from ingestion.build_kb4 import collect_chunks
    folder = tmp_path / "sales_info"
    folder.mkdir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plans"
    ws.append(["Plan", "Price", "Seats", "Price"])            # repeated header name
    ws.append(["Starter", 9.0, 1, None])
    ws.append([])                                              # blank row
    ws.append(["Pro", 49.5, "=2*5", datetime.datetime(2026, 1, 31)])
    wb.create_sheet("Empty")
    faq = wb.create_sheet("FAQ")
    faq.append(["Question", "Answer"])
    faq.append(["Do you offer refunds?", "Within 30 days."])
    wb.save(folder / "pricing.xlsx")

    one = openpyxl.Workbook()
    one.active.append(["Region", "Owner"])
    one.active.append(["EMEA", "Dana"])
    one.save(folder / "regions.xlsx")

    chunks = {c["source_doc_id"]: [] for c in collect_chunks(tmp_path)}
    for c in collect_chunks(tmp_path):
        chunks[c["source_doc_id"]].append(c["chunk_text"])
    assert chunks["sales_info/pricing.xlsx"] == [
        "Pricing > Plans\nPlan: Starter\nPrice: 9\nSeats: 1\n\nPlan: Pro\nPrice: 49.5\nPrice 2: 2026-01-31",
        "Pricing > FAQ\nQ: Do you offer refunds?\nA: Within 30 days."]
    # a single sheet gets no "## sheet" section; formulas without a cached result are dropped
    assert chunks["sales_info/regions.xlsx"] == ["Regions\nRegion: EMEA\nOwner: Dana"]
