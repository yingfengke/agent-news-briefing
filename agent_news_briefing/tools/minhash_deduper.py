"""
minhash_deduper.py — MinHash Content Fingerprint Deduplication Tool
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class MinhashDeduperTool(BaseTool):
    """Remove near-duplicate content using MinHash + LSH fingerprints."""

    name = "minhash_deduper"
    description = "Content fingerprint deduplication via MinHash+LSH"

    def run(self, items: list, **kwargs) -> ToolResult:
        try:
            from deduplicator import MinhashDeduper
            deduper = MinhashDeduper()
            kept = [it for it in items if not deduper.is_duplicate(it)]
            removed = len(items) - len(kept)
            return ToolResult(True, data={"kept": kept, "removed": removed})
        except Exception as e:
            return ToolResult(False, error=f"MinHash dedup failed: {e}")
