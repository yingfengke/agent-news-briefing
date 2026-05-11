"""
filter_agent.py — Filter Agent

Responsibility: deduplicate and filter raw news.
Replaces: deduplicator.py
Tools used: url_deduper, minhash_deduper, embedding_api
"""

from agent_news_briefing.core.agent import BaseAgent
from agent_news_briefing.models import BriefingContext


class FilterAgent(BaseAgent):
    """Filter Agent — removes duplicates and filters low-quality news."""

    name = "filter"

    def execute(self, context: BriefingContext) -> BriefingContext:
        context.log("filter", "started", "ok")

        items = context.raw_items
        if not items:
            context.log("filter", "skip", "ok", "no raw items to filter")
            context.clean_items = []
            return context

        total_before = len(items)
        total_removed = 0

        # 1. URL dedup
        url_result = self.use_tool("url_deduper", items=items)
        if url_result:
            data = url_result.data
            items = data["kept"]
            total_removed += data["removed"]
            context.log("filter", "url_deduper", "ok", f"removed {data['removed']}")
        else:
            context.log("filter", "url_deduper", "fail", url_result.error)

        if not items:
            context.clean_items = []
            return context

        # 2. MinHash content dedup
        mh_result = self.use_tool("minhash_deduper", items=items)
        if mh_result:
            data = mh_result.data
            items = data["kept"]
            total_removed += data["removed"]
            context.log("filter", "minhash_deduper", "ok", f"removed {data['removed']}")
        else:
            context.log("filter", "minhash_deduper", "fail", mh_result.error)

        if not items:
            context.clean_items = []
            return context

        # 3. Credibility filtering (inline — uses original deduplicator)
        try:
            from deduplicator import CredibilityFilter
            cf = CredibilityFilter()
            before = len(items)
            items = [it for it in items if not cf.should_filter(it)]
            removed = before - len(items)
            total_removed += removed
            if removed:
                context.log("filter", "credibility_filter", "ok", f"removed {removed}")
        except Exception as e:
            context.log("filter", "credibility_filter", "warn", str(e))

        # Write results
        context.clean_items = items
        context.log("filter", "done", "ok",
                     f"{total_before} -> {len(items)} (removed {total_removed})")
        return context
