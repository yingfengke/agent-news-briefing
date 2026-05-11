"""
smtp_sender.py — SMTP Email Sender Tool
"""

from agent_news_briefing.core.tool import BaseTool, ToolResult
from agent_news_briefing import config


class SmtpSenderTool(BaseTool):
    """Send email via QQ Mail SMTP."""

    name = "smtp_sender"
    description = "Send email via SMTP"

    def run(self, **kwargs) -> ToolResult:
        try:
            from send_email import send
            ok = send()
            return ToolResult(ok, data={"sent": ok})
        except Exception as e:
            return ToolResult(False, error=f"SMTP send failed: {e}")
