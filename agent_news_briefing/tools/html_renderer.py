"""
html_renderer.py — HTML Email Renderer Tool

Generates the HTML email from AI output.
"""

import os

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class HtmlRendererTool(BaseTool):
    """Render news items into HTML email and web page."""

    name = "html_renderer"
    description = "Generate HTML email and web page from AI output"

    def run(self, news_items: list, daily_analysis: str = "",
            projects: list = None, style_name: str = "",
            trivia: str = "", **kwargs) -> ToolResult:
        try:
            from generate_briefing import write_html, generate_email_html
            from config import get_random_trivia
            from models import FilterReport

            # Fall through: the current generate_email_html works as-is
            filter_report = FilterReport(total_input=len(news_items))
            filter_report.total_output = len(news_items)

            ok = generate_email_html(
                news_items, daily_analysis, projects or [],
                filter_report=filter_report,
                style_name=style_name,
                trivia=trivia or get_random_trivia(),
            )
            if not ok:
                return ToolResult(False, error="Email generation returned False")

            return ToolResult(True, data={"html_file": config.EMAIL_OUTPUT})

        except Exception as e:
            return ToolResult(False, error=f"HTML render failed: {e}")
