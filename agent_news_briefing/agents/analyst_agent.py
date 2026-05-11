"""
analyst_agent.py — Analyst Agent

Responsibility: analyze clean news, generate summaries, detect trends.
Replaces: AI analysis portion of generate_briefing.py
Tools used: llm_api, embedding_api
RAG: queries KnowledgeBase for historical context
"""

import json
import re

from agent_news_briefing.core.agent import BaseAgent
from agent_news_briefing.models import BriefingContext
from agent_news_briefing.rag.knowledge_base import KnowledgeBase


class AnalystAgent(BaseAgent):
    """Analyst Agent — uses LLM + RAG to produce structured analysis."""

    name = "analyst"

    def __init__(self):
        super().__init__()
        self.knowledge_base = KnowledgeBase()

    def execute(self, context: BriefingContext) -> BriefingContext:
        context.log("analyst", "started", "ok")

        items = context.clean_items
        if not items:
            context.log("analyst", "skip", "ok", "no clean items to analyze")
            return context

        # 1. Build prompt
        zh_items = [it for it in items if it.lang == "zh"]
        en_items = [it for it in items if it.lang == "en"]
        feed_items = en_items[:12] + zh_items[:10]

        lines = ["Below are today's news, please process per your system prompt.\n"]
        for i, item in enumerate(feed_items, 1):
            content_short = (item.content or "")[:80]
            time_info = f" ({item.published_at[:10]})" if item.published_at else ""
            lines.append(f"{i}. [{item.source}]{time_info} {item.title}")
            lines.append(f"   summary: {content_short}")
            lines.append(f"   link: {item.url}\n")

        # 2. Inject RAG context
        history = self.knowledge_base.get_history_titles()
        if len(history) > 10:
            history = history[-10:]
        if history:
            lines.append("\n---\n[Previously covered] avoid repeating similar topics:\n")
            for t in history:
                lines.append(f"- {t}")

        user_content = "\n".join(lines)

        # 3. Call LLM
        from config import get_random_style
        style_name, system_prompt = get_random_style()

        llm_result = self.use_tool("llm_api",
                                    system_prompt=system_prompt,
                                    user_content=user_content)
        if not llm_result:
            context.log("analyst", "llm_api", "fail", llm_result.error)
            context.errors.append(f"LLM analysis failed: {llm_result.error}")
            return context

        raw_output = llm_result.data

        # 4. Parse JSON from LLM output
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_output)
            if m:
                parsed = json.loads(m.group(1).strip())
            else:
                start = raw_output.find("{")
                end = raw_output.rfind("}")
                if start != -1 and end > start:
                    parsed = json.loads(raw_output[start:end+1])
                else:
                    context.log("analyst", "parse", "fail", "Could not parse LLM JSON output")
                    context.errors.append("LLM output parsing failed")
                    return context

        context.ai_result = parsed
        context.daily_analysis = parsed.get("daily_analysis", "")

        # 5. Store results into RAG for future use
        try:
            for group in ["international", "china"]:
                for it in parsed.get(group, []):
                    self.knowledge_base.store(
                        title=it.get("title", ""),
                        summary=it.get("summary", ""),
                        source=it.get("source", "AI"),
                        url=it.get("link", ""),
                    )
        except Exception as e:
            context.log("analyst", "rag_store", "warn", str(e))

        # 6. Fetch GitHub trending
        trending = self._fetch_trending()
        context.trending_projects = trending

        intl = len(parsed.get("international", []))
        cn = len(parsed.get("china", []))
        context.log("analyst", "done", "ok",
                     f"LLM: {intl} intl + {cn} china, RAG: {self.knowledge_base.count} entries")
        return context

    def _fetch_trending(self) -> list:
        """Fetch GitHub trending projects."""
        try:
            from generate_briefing import fetch_github_trending
            return fetch_github_trending() or []
        except Exception:
            return []
