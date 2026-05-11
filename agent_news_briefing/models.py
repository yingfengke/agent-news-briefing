"""
models.py — shared data models for the multi-agent system

Reuses the same NewsItem as the original system for compatibility.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    """Unified news item — identical to original models.NewsItem for drop-in compatibility."""

    id: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    source: str = ""
    lang: str = "zh"
    source_type: str = "rss"  # rss | crawler
    crawled_at: str = ""
    published_at: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id and self.url:
            self.id = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]


@dataclass
class BriefingContext:
    """
    Context object passed between agents in the pipeline.
    Each agent reads from and writes to this shared context.
    """

    raw_items: list[NewsItem] = field(default_factory=list)
    clean_items: list[NewsItem] = field(default_factory=list)
    ai_result: Optional[dict] = None
    daily_analysis: str = ""
    trending_projects: list[dict] = field(default_factory=list)
    email_html: str = ""
    email_sent: bool = False
    errors: list[str] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)  # [{agent, action, status}]

    def log(self, agent: str, action: str, status: str = "ok", detail: str = ""):
        self.timeline.append({
            "agent": agent,
            "action": action,
            "status": status,
            "detail": detail,
            "ts": datetime.now().isoformat(),
        })
