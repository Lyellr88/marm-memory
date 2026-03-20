"""Semantic search with sentence transformers"""
import numpy as np
from typing import List, Tuple, Optional
import pickle
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SemanticSearch:
    """Semantic search using sentence transformers"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", cache_dir: str = ".marm-cli/embeddings"):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = None
        self._lazy_load = True  # Lazy load to speed up startup

    def _load_model(self):
        """Lazy load the sentence transformer model"""
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading sentence transformer model: {self.model_name}")
                self.model = SentenceTransformer(self.model_name)
                logger.info("Model loaded successfully")
            except ImportError:
                logger.error("sentence-transformers not installed")
                raise
            except Exception as e:
                logger.error(f"Error loading model: {e}")
                raise

    def get_embedding(self, text: str) -> np.ndarray:
        """Get embedding vector for text"""
        if self.model is None:
            self._load_model()

        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    def get_embedding_bytes(self, text: str) -> bytes:
        """Get embedding as bytes for SQLite storage"""
        embedding = self.get_embedding(text)
        return pickle.dumps(embedding)

    @staticmethod
    def embedding_from_bytes(data: bytes) -> np.ndarray:
        """Convert bytes back to embedding array"""
        return pickle.loads(data)

    def cosine_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Calculate cosine similarity between two embeddings"""
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def find_similar(
        self,
        query_embedding: np.ndarray,
        candidate_embeddings: List[Tuple[int, np.ndarray]],
        top_k: int = 5,
        threshold: float = 0.3
    ) -> List[Tuple[int, float]]:
        """
        Find most similar embeddings to query

        Args:
            query_embedding: Query embedding vector
            candidate_embeddings: List of (id, embedding) tuples
            top_k: Number of results to return
            threshold: Minimum similarity score (0.0 to 1.0)

        Returns:
            List of (id, similarity_score) tuples sorted by similarity
        """
        if not candidate_embeddings:
            return []

        similarities = []
        for idx, candidate in candidate_embeddings:
            similarity = self.cosine_similarity(query_embedding, candidate)
            if similarity >= threshold:
                similarities.append((idx, similarity))

        # Sort by similarity (highest first)
        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:top_k]

    def batch_encode(self, texts: List[str]) -> List[np.ndarray]:
        """Encode multiple texts at once (faster than one-by-one)"""
        if self.model is None:
            self._load_model()

        try:
            embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            return [emb for emb in embeddings]
        except Exception as e:
            logger.error(f"Error in batch encoding: {e}")
            raise

    def search_text(
        self,
        query: str,
        corpus: List[Tuple[int, str]],
        top_k: int = 5,
        threshold: float = 0.3
    ) -> List[Tuple[int, float, str]]:
        """
        Search for similar texts in corpus

        Args:
            query: Search query text
            corpus: List of (id, text) tuples to search
            top_k: Number of results
            threshold: Minimum similarity

        Returns:
            List of (id, score, text) tuples
        """
        if not corpus:
            return []

        # Get query embedding
        query_embedding = self.get_embedding(query)

        # Get corpus embeddings
        corpus_texts = [text for _, text in corpus]
        corpus_embeddings = self.batch_encode(corpus_texts)

        # Create candidate list with IDs
        candidates = [(corpus[i][0], corpus_embeddings[i]) for i in range(len(corpus))]

        # Find similar
        results = self.find_similar(query_embedding, candidates, top_k, threshold)

        # Add text to results
        id_to_text = {idx: text for idx, text in corpus}
        return [(idx, score, id_to_text[idx]) for idx, score in results]

    def detect_topic_shift(
        self,
        current_embedding: np.ndarray,
        new_embedding: np.ndarray,
        threshold: float = 0.3
    ) -> bool:
        """
        Detect if there's a significant topic shift

        Args:
            current_embedding: Current topic embedding
            new_embedding: New message embedding
            threshold: Similarity threshold (below = topic shift)

        Returns:
            True if topic shifted significantly
        """
        similarity = self.cosine_similarity(current_embedding, new_embedding)
        return similarity < threshold
