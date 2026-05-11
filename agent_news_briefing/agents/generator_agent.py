"""
generator_agent.py — Generator Agent

Responsibility: generate HTML email and send it.
Replaces: email generation portion of generate_briefing.py + send_email.py
Tools used: html_renderer, smtp_sender
"""

from config import get_random_trivia

from agent_news_briefing.core.agent import BaseAgent
from agent_news_briefing.models import BriefingContext


class GeneratorAgent(BaseAgent):
    """Generator Agent — produces HTML and sends email."""

    name = "generator"

    def execute(self, context: BriefingContext) -> BriefingContext:
        context.log("generator", "started", "ok")

        # 1. Build final items list from AI result
        final_items = []
        ai_result = context.ai_result
        if ai_result:
            if "international" in ai_result and "china" in ai_result:
                for it in ai_result.get("international", []):
                    final_items.append(self._make_item(it, "international"))
                for it in ai_result.get("china", []):
                    final_items.append(self._make_item(it, "china"))
            elif "items" in ai_result:
                for it in ai_result["items"]:
                    final_items.append(self._make_item(it))

        if not final_items:
            context.log("generator", "skip", "ok", "no items to generate")
            return context

        # 2. Render HTML
        html_result = self.use_tool(
            "html_renderer",
            news_items=final_items,
            daily_analysis=context.daily_analysis,
            projects=context.trending_projects,
            trivia=get_random_trivia(),
        )
        if not html_result:
            context.log("generator", "html_renderer", "fail", html_result.error)
            context.errors.append(f"HTML render: {html_result.error}")
            return context

        context.log("generator", "html_renderer", "ok", f"{len(final_items)} items rendered")

        # 3. Send email
        smtp_result = self.use_tool("smtp_sender")
        if smtp_result:
            context.email_sent = True
            context.log("generator", "smtp_sender", "ok", "email sent")
        else:
            context.log("generator", "smtp_sender", "fail", smtp_result.error)
            context.errors.append(f"SMTP send: {smtp_result.error}")

        context.log("generator", "done", "ok",
                     f"rendered {len(final_items)} items, sent={context.email_sent}")
        return context

    @staticmethod
    def _make_item(it: dict, region: str = "") -> dict:
        """Build a dict item for the HTML renderer."""
        summary = it.get("summary", "")
        link = it.get("link") or it.get("url") or ""
        item = {
            "title": it.get("title", ""),
            "summary": summary,
            "link": link,
            "source": it.get("source", "AI"),
        }
        if region:
            item["region"] = region
        return item
