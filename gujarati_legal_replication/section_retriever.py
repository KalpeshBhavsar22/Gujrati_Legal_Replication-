"""
Section-wise Retrieval Module

Retrieves similar sections by:
- Section type
- Legal role
- Numbering structure
- Template similarity

NOT random chunk retrieval or semantic-only retrieval.
"""

import json
import logging
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from .structured_parser import JudgementSchema, Section

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """A single retrieval result."""
    section: Section
    source_file: str
    score: float
    section_type: str


class SectionIndex:
    """
    Index of sections organized by type for structured retrieval.
    Uses FAISS for vector similarity within section types.
    Embeddings via Google Gemini text-embedding-004 (free API).
    """
    
    def __init__(self, config):
        self.config = config
        self.indices = {}  # section_type -> FAISS index
        self.metadata = {}  # section_type -> list of metadata dicts
        self._initialized = False
        self._api_key = None
    
    def _get_api_key(self):
        """Get Gemini API key."""
        if self._api_key is None:
            import os
            self._api_key = os.environ.get("GEMINI_API_KEY")
            if not self._api_key:
                raise ValueError("GEMINI_API_KEY not set")
        return self._api_key
    
    def _get_embeddings_batch(self, texts: list) -> np.ndarray:
        """Get embeddings for a batch of texts using Gemini API."""
        import urllib.request
        import json as json_mod
        
        api_key = self._get_api_key()
        url = (f"{self.config.embedding_api_base}"
               f"models/{self.config.embedding_model}:batchEmbedContents"
               f"?key={api_key}")
        
        # Gemini batch embed request format
        requests_body = {
            "requests": [
                {
                    "model": f"models/{self.config.embedding_model}",
                    "content": {"parts": [{"text": t[:2048]}]},  # max 2048 chars
                    "taskType": "RETRIEVAL_DOCUMENT",
                }
                for t in texts
            ]
        }
        
        data = json_mod.dumps(requests_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req) as resp:
            result = json_mod.loads(resp.read())
        
        embeddings = [e["values"] for e in result["embeddings"]]
        return np.array(embeddings, dtype=np.float32)
    
    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for a single text."""
        return self._get_embeddings_batch([text])[0]
    
    def _get_query_embedding(self, text: str) -> np.ndarray:
        """Get query embedding."""
        import urllib.request
        import json as json_mod
        
        api_key = self._get_api_key()
        url = (f"{self.config.embedding_api_base}"
               f"models/{self.config.embedding_model}:embedContent"
               f"?key={api_key}")
        
        body = {
            "model": f"models/{self.config.embedding_model}",
            "content": {"parts": [{"text": text[:2048]}]},
            "taskType": "RETRIEVAL_QUERY",
        }
        
        data = json_mod.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req) as resp:
            result = json_mod.loads(resp.read())
        
        return np.array(result["embedding"]["values"], dtype=np.float32)
    
    def build_index(self, schemas: list):
        """
        Build section-type-specific indices from parsed schemas.
        
        Args:
            schemas: List of (JudgementSchema, source_file) tuples
        """
        import faiss
        
        # Group sections by type
        sections_by_type = {}
        for schema, source_file in schemas:
            for section in schema.sections:
                if section.section_type not in sections_by_type:
                    sections_by_type[section.section_type] = []
                sections_by_type[section.section_type].append((section, source_file))
        
        # Build FAISS index for each section type
        for section_type, section_list in sections_by_type.items():
            logger.info(f"Building index for section type: {section_type} ({len(section_list)} sections)")
            
            # Generate embeddings via Gemini API
            texts = []
            for section, _ in section_list:
                text = f"{section.title}\n{section.content[:1000]}"
                texts.append(text)
            
            # Batch embed (Gemini supports up to 100 per batch)
            all_embeddings = []
            for i in range(0, len(texts), 100):
                batch = texts[i:i+100]
                embeddings = self._get_embeddings_batch(batch)
                all_embeddings.append(embeddings)
            
            embeddings = np.concatenate(all_embeddings, axis=0) if len(all_embeddings) > 1 else all_embeddings[0]
            
            # Create FAISS index
            dim = embeddings.shape[1]
            index = faiss.IndexFlatIP(dim)  # Inner product for cosine similarity
            # Normalize for cosine similarity
            faiss.normalize_L2(embeddings)
            index.add(embeddings)
            
            self.indices[section_type] = index
            self.metadata[section_type] = [
                {
                    "section": section,
                    "source_file": source_file,
                    "section_type": section_type,
                }
                for section, source_file in section_list
            ]
        
        self._initialized = True
        logger.info(f"Built indices for {len(self.indices)} section types")
    
    def save_index(self, path: Path):
        """Save indices to disk."""
        import faiss
        
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        for section_type, index in self.indices.items():
            safe_name = section_type.replace(" ", "_")
            faiss.write_index(index, str(path / f"index_{safe_name}.faiss"))
        
        # Save metadata
        meta_to_save = {}
        for section_type, meta_list in self.metadata.items():
            meta_to_save[section_type] = [
                {
                    "source_file": m["source_file"],
                    "section_type": m["section_type"],
                    "section_id": m["section"].id,
                    "section_title": m["section"].title,
                    "section_content": m["section"].content,
                    "subsections": [
                        {"id": ss.id, "numbering": ss.numbering, "content": ss.content}
                        for ss in m["section"].subsections
                    ],
                }
                for m in meta_list
            ]
        
        meta_path = path / "metadata.json"
        meta_path.write_text(
            json.dumps(meta_to_save, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Saved indices to {path}")
    
    def load_index(self, path: Path):
        """Load indices from disk."""
        import faiss
        
        path = Path(path)
        
        # Load metadata
        meta_path = path / "metadata.json"
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        
        for section_type, meta_list in meta_data.items():
            safe_name = section_type.replace(" ", "_")
            index_path = path / f"index_{safe_name}.faiss"
            
            if index_path.exists():
                self.indices[section_type] = faiss.read_index(str(index_path))
                self.metadata[section_type] = [
                    {
                        "source_file": m["source_file"],
                        "section_type": m["section_type"],
                        "section": Section(
                            id=m["section_id"],
                            section_type=m["section_type"],
                            title=m["section_title"],
                            content=m["section_content"],
                            subsections=[],
                        ),
                    }
                    for m in meta_list
                ]
        
        self._initialized = True
        logger.info(f"Loaded {len(self.indices)} indices from {path}")


class SectionRetriever:
    """
    Retrieves similar sections using section-type-aware retrieval.
    
    Key principle: Retrieve by section type + similarity,
    NOT by random semantic chunk matching.
    """
    
    def __init__(self, config, section_index: SectionIndex):
        self.config = config
        self.index = section_index
    
    def retrieve(
        self,
        query_section: Section,
        top_k: Optional[int] = None,
    ) -> list:
        """
        Retrieve similar sections of the same type.
        
        Args:
            query_section: The section to find similar examples for
            top_k: Number of results to return
            
        Returns:
            List of RetrievalResult
        """
        top_k = top_k or self.config.top_k
        section_type = query_section.section_type
        
        # First try exact section type match
        results = self._retrieve_by_type(query_section, section_type, top_k)
        
        # If insufficient results, also search "general" type
        if len(results) < top_k and "general" in self.index.indices:
            remaining = top_k - len(results)
            general_results = self._retrieve_by_type(query_section, "general", remaining)
            results.extend(general_results)
        
        return results[:top_k]
    
    def retrieve_for_template(
        self,
        section_type: str,
        context: str = "",
        top_k: Optional[int] = None,
    ) -> list:
        """
        Retrieve example sections for a given section type.
        Used when generating from template.
        
        Args:
            section_type: Type of section to retrieve examples for
            context: Additional context for similarity matching
            top_k: Number of results
        """
        top_k = top_k or self.config.top_k
        
        if section_type not in self.index.indices:
            logger.warning(f"No index for section type: {section_type}")
            return []
        
        # Create a query from section type + context
        query_text = f"{section_type}: {context}" if context else section_type
        query_embedding = self.index._get_query_embedding(query_text)
        
        index = self.index.indices[section_type]
        scores, indices = index.search(
            query_embedding.reshape(1, -1).astype(np.float32), top_k
        )
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            meta = self.index.metadata[section_type][idx]
            results.append(RetrievalResult(
                section=meta["section"],
                source_file=meta["source_file"],
                score=float(score),
                section_type=section_type,
            ))
        
        return results
    
    def _retrieve_by_type(self, query_section: Section, section_type: str, top_k: int) -> list:
        """Retrieve from a specific section type index."""
        if section_type not in self.index.indices:
            return []
        
        # Build query from section content
        query_text = f"{query_section.title}\n{query_section.content[:500]}"
        query_embedding = self.index._get_query_embedding(query_text)
        
        index = self.index.indices[section_type]
        scores, indices = index.search(
            query_embedding.reshape(1, -1).astype(np.float32), top_k
        )
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            meta = self.index.metadata[section_type][idx]
            results.append(RetrievalResult(
                section=meta["section"],
                source_file=meta["source_file"],
                score=float(score),
                section_type=section_type,
            ))
        
        return results
