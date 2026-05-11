"""
agent.py — Base Agent class

An Agent is an autonomous unit with:
  - A name and role description
  - A registry of Tools it can use
  - An execute(context) method that decides what to do
  - Error handling and retry logic built in

Agents don't call each other directly. They write to a shared
BriefingContext, and the Orchestrator decides the pipeline order.
"""

import time
from abc import ABC, abstractmethod
from typing import Any

from .tool import BaseTool, ToolResult
from agent_news_briefing.models import BriefingContext
from agent_news_briefing import config


class BaseAgent(ABC):
    """
    Abstract base class for all agents.

    Subclasses must implement:
      - name: short identifier
      - execute(context) -> BriefingContext: process and update context

    Subclasses can override:
      - setup(): called once before the first execute
      - teardown(): called once after the last execute
    """

    name: str = ""

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__
        self._tools: dict[str, BaseTool] = {}

    # --- Tool management ---

    def register_tool(self, tool: BaseTool):
        """Register a tool this agent can use."""
        self._tools[tool.name] = tool

    def register_tools(self, *tools: BaseTool):
        """Register multiple tools at once."""
        for t in tools:
            self.register_tool(t)

    def use_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Invoke a registered tool with retry logic.
        Always returns ToolResult — never raises.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(False, error=f"Tool '{tool_name}' not registered")

        for attempt in range(1, config.AGENT_MAX_RETRIES + 1):
            try:
                result = tool.run(**kwargs)
                if result.success:
                    return result
                if attempt < config.AGENT_MAX_RETRIES:
                    time.sleep(config.AGENT_RETRY_DELAY)
            except Exception as e:
                if attempt < config.AGENT_MAX_RETRIES:
                    time.sleep(config.AGENT_RETRY_DELAY)
                else:
                    return ToolResult(False, error=f"{tool_name} failed after {attempt} attempts: {e}")

        return ToolResult(False, error=f"{tool_name} exhausted {config.AGENT_MAX_RETRIES} retries")

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    # --- Lifecycle ---

    def setup(self):
        """Override to perform one-time initialization."""
        pass

    def teardown(self):
        """Override to perform one-time cleanup."""
        pass

    # --- Core ---

    @abstractmethod
    def execute(self, context: BriefingContext) -> BriefingContext:
        """
        Execute the agent's task.
        Reads from context, processes, writes results back.
        """
        ...

    def __repr__(self):
        tools = ", ".join(self._tools.keys()) or "no tools"
        return f"<Agent: {self.name} [{tools}]>"
