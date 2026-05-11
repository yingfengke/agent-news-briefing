"""
knowledge_base.py — RAG Knowledge Base

Stores past briefings as vector embeddings for:
  1. Historical deduplication — avoid reporting the same story twice
  2. Context injection — analyst agent can pull similar past stories
  3. Trend detection — notice when a topic recurs

Current implementation: JSON file + in-memory cosine similarity.
Future upgrade path: replace with real vector DB (ChromaDB / Pinecone).
"""

import json
import os
import re
from datetime import datetime
from typing import Optional

import numpy as np

from agent_news_briefing import config
from agent_news_briefing.models import NewsItem


class KnowledgeBase:
    """
    Lightweight RAG store.

    Stores entries as dicts with title, summary, source, embedding vector.
    Query returns top-K most similar entries via cosine similarity.
    """

    def __init__(self, db_path: str = config.RAG_DB_PATH):
        self.db_path = db_path
        self._entries: list[dict] = []
        self._load()

    # ---- persistence ----

    def _load(self):
        try:
            with open(self.db_path, "r") as f:
                self._entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._entries = []

    def _save(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with open(self.db_path, "w") as f:
            json.dump(self._entries, f, ensure_ascii=False, indent=2)

    # ---- public API ----

    def store(
        self,
        title: str,
        summary: str,
        source: str,
        url: str,
        embedding: Optional[list[float]] = None,
    ):
        """Store a news item into the knowledge base."""
        entry = {
            "title": title,
            "summary": summary,
            "source": source,
            "url": url,
            "embedding": embedding,
            "stored_at": datetime.now().isoformat(),
        }
        # Avoid duplicates by URL
        existing = [i for i, e in enumerate(self._entries) if e.get("url") == url]
        if existing:
            self._entries[existing[0]] = entry
        else:
            self._entries.append(entry)
        self._save()

    def store_batch(self, items: list[NewsItem], embeddings: Optional[list[list[float]]] = None):
        """Store multiple items at once."""
        for i, item in enumerate(items):
            emb = embeddings[i] if embeddings and i < len(embeddings) else None
            self.store(item.title, item.content[:200], item.source, item.url, emb)

    def query(self, text: str, top_k: int = config.RAG_TOP_K) -> list[dict]:
        """
        Find top-K most similar entries by keyword overlap.
        (Future: replace with real vector similarity.)
        """
        if not self._entries:
            return []

        # Simple TF overlap scoring (placeholder for real embedding search)
        keywords = set(re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower()))
        scored = []
        for entry in self._entries:
            body = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
            overlap = len(keywords & set(re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", body)))
            scored.append((overlap, entry))

        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_k] if _ > 0]

    def get_history_titles(self) -> list[str]:
        """Return all stored titles (for AI prompt context)."""
        return [e.get("title", "") for e in self._entries[-50:]]

    @property
    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries = []
        self._save()
