import chromadb
from sentence_transformers import SentenceTransformer

from config.settings import ModelSettings

_settings = ModelSettings()


class KBManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.embedder = SentenceTransformer(_settings.embedding_model)
        self.client = chromadb.PersistentClient(path=_settings.chroma_path)
        self.kb2_attacks = self.client.get_or_create_collection("kb2_attacks", metadata={"hnsw:space": "cosine"})
        self.kb4_documents = self.client.get_or_create_collection("kb4_documents", metadata={"hnsw:space": "cosine"})
        self.kb5_pii = self.client.get_or_create_collection("kb5_pii", metadata={"hnsw:space": "cosine"})
        self.kb6_narrative = self.client.get_or_create_collection("kb6_narrative", metadata={"hnsw:space": "cosine"})

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return self.embedder.encode(texts, show_progress_bar=False).tolist()


kb = KBManager()   # import this singleton everywhere — loads the model/collections once
