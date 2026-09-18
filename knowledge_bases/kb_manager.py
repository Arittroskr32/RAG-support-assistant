"""Shared embedder + ChromaDB collections for every KB.

`kb` is a lazy proxy: importing this module is cheap, and the embedding model / Chroma
client load on first attribute access. Tests swap in a fake with `set_kb(...)`.
"""
import threading

from config.settings import MODEL_SETTINGS, get_thresholds

COLLECTIONS = ("kb2_attacks", "kb4_documents", "kb5_pii", "kb6_narrative")
CHROMA_MAX_BATCH = 4000   # Chroma caps a single add()/upsert() (~5461 on default settings)


def split_windows(text: str, window_words: int, stride_words: int) -> list[str]:
    """Overlapping word windows so text past the embedder's 256-token limit is still seen.
    Short text returns [text] unchanged, so short-prompt behaviour is identical to embedding
    the whole string."""
    words = text.split()
    if len(words) <= window_words:
        return [text]
    windows, start = [], 0
    while True:
        windows.append(" ".join(words[start:start + window_words]))
        if start + window_words >= len(words):
            break
        start += stride_words
    return windows


class KBManager:
    def __init__(self, settings=MODEL_SETTINGS):
        import chromadb
        from sentence_transformers import SentenceTransformer

        self.settings = settings
        self.embedder = SentenceTransformer(settings.embedding_model)
        self.client = chromadb.PersistentClient(path=settings.chroma_path)
        self._lock = threading.Lock()
        for name in COLLECTIONS:
            setattr(self, name, self._get_or_create(name))

    def _get_or_create(self, name):
        try:   # Chroma >= 1.0 collection configuration
            return self.client.get_or_create_collection(name, configuration={"hnsw": {"space": "cosine"}})
        except TypeError:  # older Chroma: legacy metadata key
            return self.client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})

    def reset_collection(self, name: str):
        """Drop and recreate a collection so a rebuild never leaves stale entries behind."""
        try:
            self.client.delete_collection(name)
        except Exception:
            pass   # didn't exist yet
        coll = self._get_or_create(name)
        setattr(self, name, coll)
        return coll

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        with self._lock:   # SentenceTransformer.encode isn't guaranteed thread-safe
            return self.embedder.encode(texts, show_progress_bar=False).tolist()

    def embed_windows(self, text: str, cfg=None) -> list[list[float]]:
        cfg = cfg or get_thresholds()
        if not cfg.enable_windowed_embedding:
            return self.embed(text)
        return self.embed(split_windows(text, cfg.embed_window_words, cfg.embed_window_stride))

    def add_batched(self, collection, ids, documents, embeddings, metadatas, upsert=False):
        op = collection.upsert if upsert else collection.add
        for i in range(0, len(ids), CHROMA_MAX_BATCH):
            op(ids=ids[i:i + CHROMA_MAX_BATCH], documents=documents[i:i + CHROMA_MAX_BATCH],
               embeddings=embeddings[i:i + CHROMA_MAX_BATCH], metadatas=metadatas[i:i + CHROMA_MAX_BATCH])


def nearest(collection, embeddings: list[list[float]]):
    """Minimum cosine distance over one or more query embeddings (e.g. the windows of a
    long prompt). Returns (distance, id, metadata); distance 1.0 when the collection is
    empty."""
    if not embeddings or collection.count() == 0:
        return 1.0, None, None
    res = collection.query(query_embeddings=embeddings, n_results=1, include=["distances", "metadatas"])
    best = (1.0, None, None)
    for dists, ids, metas in zip(res.get("distances") or [], res.get("ids") or [], res.get("metadatas") or []):
        if dists and dists[0] < best[0]:
            best = (dists[0], ids[0], metas[0] if metas else None)
    return best


class _LazyKB:
    """Proxy that builds the real KBManager on first use."""
    _instance = None
    _init_lock = threading.Lock()

    def _get(self):
        if _LazyKB._instance is None:
            with _LazyKB._init_lock:
                if _LazyKB._instance is None:
                    _LazyKB._instance = KBManager()
        return _LazyKB._instance

    def __getattr__(self, item):
        return getattr(self._get(), item)


def set_kb(instance) -> None:
    """Replace the shared KB (tests, or a differently-configured instance)."""
    _LazyKB._instance = instance


kb = _LazyKB()   # import this everywhere — loads the model/collections once, on first use
