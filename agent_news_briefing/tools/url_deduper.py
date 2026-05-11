"""
url_deduper.py — URL Deduplication Tool

Uses SHA256 hash database from original deduplicator.
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class UrlDeduperTool(BaseTool):
    """Remove duplicate URLs using SHA256 hash database."""

    name = "url_deduper"
    description = "URL-level deduplication"

    def run(self, items: list, **kwargs) -> ToolResult:
        try:
            from deduplicator import UrlDeduper
            deduper = UrlDeduper()
            kept = [it for it in items if not deduper.is_duplicate(it)]
            deduper.flush()
            removed = len(items) - len(kept)
            return ToolResult(True, data={"kept": kept, "removed": removed})
        except Exception as e:
            return ToolResult(False, error=f"URL dedup failed: {e}")
