"""Run once, and re-run any time data/ changes."""
from ingestion.chunkers import chunk_document
from ingestion.loaders import load_documents
from ingestion.metadata_tagger import tag_chunk
from knowledge_bases.kb_manager import kb


def build(data_dir="data/"):
    all_chunks = []
    for doc in load_documents(data_dir):
        for raw_chunk in chunk_document(doc["text"], doc["document_type"]):
            all_chunks.append(tag_chunk(raw_chunk, doc["document_type"], doc["source_doc_id"]))

    if not all_chunks:
        print("No documents found under", data_dir)
        return

    embeddings = kb.embed([c["chunk_text"] for c in all_chunks])
    kb.kb4_documents.add(
        ids=[c["chunk_id"] for c in all_chunks],
        documents=[c["chunk_text"] for c in all_chunks],
        embeddings=embeddings,
        metadatas=[{"document_type": c["document_type"], "clearance_level": c["clearance_level"],
                    "tenant_id": c["tenant_id"], "source_doc_id": c["source_doc_id"]} for c in all_chunks],
    )
    print(f"KB-4 populated with {len(all_chunks)} chunks from {data_dir}")


if __name__ == "__main__":
    build()
