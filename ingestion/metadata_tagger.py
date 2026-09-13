import hashlib

CLEARANCE_BY_TYPE = {
    "public_faq": 0, "product_info": 1, "company_info": 2,
    "developer_info": 3, "sales_info": 4,
}


def tag_chunk(chunk_text: str, document_type: str, source_doc_id: str, tenant_id: str = "default"):
    chunk_id = hashlib.sha256(f"{source_doc_id}:{chunk_text[:50]}".encode()).hexdigest()[:16]
    return {
        "chunk_id": chunk_id, "chunk_text": chunk_text, "document_type": document_type,
        "clearance_level": CLEARANCE_BY_TYPE.get(document_type, 4),
        "tenant_id": tenant_id, "source_doc_id": source_doc_id,
    }
