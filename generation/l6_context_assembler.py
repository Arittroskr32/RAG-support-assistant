def tag_context(retrieved):
    blocks = []
    for i, (text, meta) in enumerate(retrieved):
        blocks.append(
            f"[DOCUMENT: {meta.get('source_doc_id', 'unknown')} | TRUST: internal | "
            f"CITATION: c{i + 1}] {text} [/DOCUMENT]"
        )
    return "\n\n".join(blocks)
