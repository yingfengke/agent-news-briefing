"""
orchestrator_agent.py — Orchestrator Agent

The conductor. Decides the pipeline order, delegates to specialized agents,
handles failures gracefully, and produces the final report.

Pipeline:
  1. Scout Agent    → collect raw data
  2. Filter Agent   → deduplicate and filter
  3. Analyst Agent  → AI analysis + RAG
  4. Generator Agent → HTML + email

Each step is optional — if scout fails, filter runs on empty data.
"""

import time
from datetime import datetime

from agent_news_briefing.core.agent import BaseAgent
from agent_news_briefing.models import BriefingContext
from agent_news_briefing import config


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent — coordinates the full briefing pipeline.

    Registers sub-agents, executes them in order, and reports results.
    """

    name = "orchestrator"

    def __init__(self):
        super().__init__()
        self._agents: list[BaseAgent] = []

    def register_agent(self, agent: BaseAgent):
        """Add an agent to the pipeline (in order)."""
        self._agents.append(agent)

    def register_agents(self, *agents: BaseAgent):
        """Add multiple agents at once."""
        for a in agents:
            self.register_agent(a)

    def execute(self, context: BriefingContext) -> BriefingContext:
        start = datetime.now()
        print(f"\n{'=' * 55}")
        print(f"  Orchestrator — multi-agent briefing pipeline")
        print(f"  Agents: {', '.join(a.name for a in self._agents)}")
        print(f"  Started: {start.isoformat()[:19]}")
        print(f"{'=' * 55}")

        context.log("orchestrator", "started", "ok")

        for i, agent in enumerate(self._agents, 1):
            print(f"\n  --- Step {i}/{len(self._agents)}: {agent.name} ---")

            # Setup
            try:
                agent.setup()
            except Exception as e:
                print(f"  [warn] {agent.name} setup failed: {e}")

            # Execute with timeout guard
            step_start = time.time()
            try:
                context = agent.execute(context)
                elapsed = time.time() - step_start
                print(f"  [{agent.name}] done in {elapsed:.1f}s")
            except Exception as e:
                elapsed = time.time() - step_start
                print(f"  [{agent.name}] failed after {elapsed:.1f}s: {e}")
                context.errors.append(f"{agent.name}: {e}")
                context.log(agent.name, "execute", "fail", str(e))

            # Teardown
            try:
                agent.teardown()
            except Exception as e:
                print(f"  [warn] {agent.name} teardown failed: {e}")

        # Final summary
        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n{'=' * 55}")
        print(f"  Pipeline complete in {elapsed:.1f}s")
        print(f"  Raw items: {len(context.raw_items)}")
        print(f"  Clean items: {len(context.clean_items)}")
        print(f"  AI analysis: {'yes' if context.daily_analysis else 'no'}")
        print(f"  Email sent: {context.email_sent}")
        print(f"  Errors: {len(context.errors)}")
        if context.errors:
            for e in context.errors[-5:]:
                print(f"    - {e}")
        print(f"{'=' * 55}")

        context.log("orchestrator", "done", "ok",
                     f"{elapsed:.1f}s, {len(context.errors)} errors")
        return context
