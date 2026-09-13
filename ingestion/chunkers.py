import re


def chunk_qa_pairs(text: str):
    """Keeps each blank-line-separated Q/A block whole — never split mid-answer."""
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def chunk_recursive(text: str, chunk_size: int = 450, overlap: int = 60):
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start = end - overlap
    return chunks


def chunk_document(text: str, document_type: str):
    if document_type == "public_faq":
        return chunk_qa_pairs(text)
    return chunk_recursive(text)
