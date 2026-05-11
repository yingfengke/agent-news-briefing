"""
rss_fetcher.py — RSS Fetcher Tool

Wraps the original collector.RSS fetching logic.
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class RssFetcherTool(BaseTool):
    """Fetch and parse RSS feeds from configured sources."""

    name = "rss_fetcher"
    description = "Fetch news from RSS feeds"

    def run(self, source_name: str = "", **kwargs) -> ToolResult:
        try:
            # Import original implementation
            from collector import _fetch, _parse_rss

            items = []
            sources = config.RSS_SOURCES

            for name, url, lang in sources:
                if source_name and name != source_name:
                    continue
                try:
                    raw = _fetch(url)
                    parsed = _parse_rss(raw, name)
                    limit = config.MAX_PER_SOURCE.get(name, 3)
                    items.extend(parsed[:limit])
                except Exception as e:
                    fallback = config.RSS_FALLBACKS.get(name)
                    if fallback:
                        try:
                            raw = _fetch(fallback)
                            parsed = _parse_rss(raw, name)
                            limit = config.MAX_PER_SOURCE.get(name, 3)
                            items.extend(parsed[:limit])
                        except Exception:
                            pass

            return ToolResult(True, data=items, error="")

        except Exception as e:
            return ToolResult(False, error=f"RSS fetch failed: {e}")
