"""
scout_agent.py — Scout Agent

Responsibility: collect raw news data from all sources.
Replaces: collector.py
Tools used: rss_fetcher, web_crawler
"""

from agent_news_briefing.core.agent import BaseAgent
from agent_news_briefing.models import BriefingContext, NewsItem


class ScoutAgent(BaseAgent):
    """Scout Agent — gathers raw news from RSS feeds and web crawlers."""

    name = "scout"

    def execute(self, context: BriefingContext) -> BriefingContext:
        context.log("scout", "started", "ok")

        all_items = []

        # 1. Fetch RSS sources
        rss_result = self.use_tool("rss_fetcher")
        if rss_result:
            items = rss_result.data
            all_items.extend(items)
            context.log("scout", "rss_fetcher", "ok", f"{len(items)} items from RSS")
        else:
            context.log("scout", "rss_fetcher", "fail", rss_result.error)
            context.errors.append(f"RSS fetch: {rss_result.error}")

        # 2. Crawl dynamic websites
        crawl_result = self.use_tool("web_crawler")
        if crawl_result:
            items = crawl_result.data
            all_items.extend(items)
            context.log("scout", "web_crawler", "ok", f"{len(items)} items from crawlers")
        else:
            context.log("scout", "web_crawler", "skip", str(crawl_result.error))

        # 3. Write back to context
        context.raw_items = all_items
        context.log("scout", "done", "ok", f"{len(all_items)} total raw items")
        return context
