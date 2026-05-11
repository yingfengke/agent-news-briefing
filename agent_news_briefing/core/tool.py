"""
tool.py — Base Tool class

A Tool is a reusable capability that Agents can invoke.
Each tool wraps a specific function (fetch RSS, call LLM, send email, etc.)
and provides a standard interface for the Agent to call it.
"""

from abc import ABC, abstractmethod
from typing import Any


class ToolResult:
    """Standard result wrapper for all tool calls."""

    def __init__(self, success: bool, data: Any = None, error: str = ""):
        self.success = success
        self.data = data
        self.error = error

    def __bool__(self):
        return self.success

    def __repr__(self):
        if self.success:
            return f"<ToolResult OK: {type(self.data).__name__ if self.data else 'None'}>"
        return f"<ToolResult FAIL: {self.error[:60]}>"


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    Subclasses must implement:
      - name: short identifier
      - description: what this tool does
      - run(**kwargs) -> ToolResult: execute the tool
    """

    name: str = ""
    description: str = ""

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__

    @abstractmethod
    def run(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given parameters.
        Always returns a ToolResult — never raises.
        """
        ...

    def __repr__(self):
        return f"<Tool: {self.name}>"
