"""
web_crawler.py — Web Crawler Tool

Wraps Playwright-based crawling from original collector.
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class WebCrawlerTool(BaseTool):
    """Crawl web pages dynamically using Playwright."""

    name = "web_crawler"
    description = "Crawl dynamic websites with Playwright"

    def run(self, **kwargs) -> ToolResult:
        try:
            from collector import collect_crawler
            items = collect_crawler()
            return ToolResult(True, data=items)
        except ImportError:
            return ToolResult(False, error="Playwright not available")
        except Exception as e:
            return ToolResult(False, error=f"Crawler failed: {e}")
