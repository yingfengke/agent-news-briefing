#!/usr/bin/env python3
"""
main.py — Multi-Agent Architecture Entry Point

Usage:
    python -m agent_news_briefing.main

This is the new entry point for the multi-agent briefing system.
It replaces the original single-pipeline main() in generate_briefing.py.

Architecture:
    Orchestrator Agent
      ├── Scout Agent     (collects raw data)
      ├── Filter Agent    (deduplicates)
      ├── Analyst Agent   (LLM analysis + RAG)
      └── Generator Agent (HTML email)

All agents share a BriefingContext that flows through the pipeline.
Each agent uses Tools to perform its work.
"""

import sys
import os

# Ensure project root is on path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agent_news_briefing.models import BriefingContext
from agent_news_briefing.agents.orchestrator_agent import OrchestratorAgent
from agent_news_briefing.agents.scout_agent import ScoutAgent
from agent_news_briefing.agents.filter_agent import FilterAgent
from agent_news_briefing.agents.analyst_agent import AnalystAgent
from agent_news_briefing.agents.generator_agent import GeneratorAgent

# --- Tools ---
from agent_news_briefing.tools.rss_fetcher import RssFetcherTool
from agent_news_briefing.tools.web_crawler import WebCrawlerTool
from agent_news_briefing.tools.url_deduper import UrlDeduperTool
from agent_news_briefing.tools.minhash_deduper import MinhashDeduperTool
from agent_news_briefing.tools.embedding_api import EmbeddingApiTool
from agent_news_briefing.tools.llm_api import LlmCompletionTool
from agent_news_briefing.tools.html_renderer import HtmlRendererTool
from agent_news_briefing.tools.smtp_sender import SmtpSenderTool


def build_pipeline() -> OrchestratorAgent:
    """Assemble the full multi-agent pipeline with tools registered."""

    # --- Create tools ---
    rss_fetcher = RssFetcherTool()
    web_crawler = WebCrawlerTool()
    url_deduper = UrlDeduperTool()
    minhash_deduper = MinhashDeduperTool()
    embedding_api = EmbeddingApiTool()
    llm_api = LlmCompletionTool()
    html_renderer = HtmlRendererTool()
    smtp_sender = SmtpSenderTool()

    # --- Create agents and register their tools ---

    # Scout: data collection
    scout = ScoutAgent()
    scout.register_tools(rss_fetcher, web_crawler)

    # Filter: deduplication
    filter_agent = FilterAgent()
    filter_agent.register_tools(url_deduper, minhash_deduper, embedding_api)

    # Analyst: AI analysis + RAG
    analyst = AnalystAgent()
    analyst.register_tools(llm_api, embedding_api)

    # Generator: email output
    generator = GeneratorAgent()
    generator.register_tools(html_renderer, smtp_sender)

    # --- Assemble pipeline ---
    orchestrator = OrchestratorAgent()
    orchestrator.register_agents(scout, filter_agent, analyst, generator)

    return orchestrator


def main():
    print("=" * 55)
    print("  AI Agent 开发者晨报 — Multi-Agent Architecture v3.0")
    print(f"  Pipeline: scout -> filter -> analyst (rag) -> generator")
    print("=" * 55)

    # Build the pipeline
    orchestrator = build_pipeline()

    # Print registered agents and tools
    print(f"\nRegistered agents:")
    for agent in orchestrator._agents:
        print(f"  - {agent}")
        for tool_name in agent.list_tools():
            print(f"      tool: {tool_name}")

    # Create empty context
    context = BriefingContext()

    # Run the pipeline
    context = orchestrator.execute(context)

    # Print timeline
    print(f"\n  Timeline ({len(context.timeline)} events):")
    for entry in context.timeline[-15:]:
        status_icon = "ok" if entry["status"] == "ok" else "!!"
        print(f"    [{status_icon}] {entry['agent']}.{entry['action']}: {entry.get('detail', '')[:60]}")

    print(f"\n  Done. See email_content.html for the generated briefing.")
    return 0 if not context.errors else 1


if __name__ == "__main__":
    sys.exit(main())
