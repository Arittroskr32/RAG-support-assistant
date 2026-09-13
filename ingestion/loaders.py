from pathlib import Path


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def load_documents(data_dir: str = "data/"):
    """Walks data_dir; each top-level subfolder name becomes document_type.
    Extend with pdf/docx loaders if your real content isn't plain text/markdown."""
    root = Path(data_dir)
    for doc_type_dir in root.iterdir():
        if not doc_type_dir.is_dir() or doc_type_dir.name == "security_datasets":
            continue
        document_type = doc_type_dir.name
        for file_path in doc_type_dir.rglob("*"):
            if file_path.suffix.lower() in {".md", ".txt"}:
                yield {"text": load_text_file(file_path), "document_type": document_type,
                       "source_doc_id": str(file_path)}
